"""Archive layout, lookup, and FTS5 search.

Layout:
    <archive_dir>/<YYYY>/<YYYY-MM-DD>/<HH-MM>_<sha8>/
        audio.<ext>
        transcript.txt
        transcript.srt
        transcript.md
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import get_settings
from .db import get_conn, transaction
from .utils import now_iso, short_hash, text_sha256


@dataclass
class Recording:
    id: int
    sha256: str
    src_path: Path
    archive_path: Path
    size_bytes: int
    duration_secs: float | None
    recorded_at: str | None
    ingested_at: str

    @classmethod
    def from_row(cls, r) -> Recording:
        return cls(
            id=int(r["id"]),
            sha256=r["sha256"],
            src_path=Path(r["src_path"]),
            archive_path=Path(r["archive_path"]),
            size_bytes=int(r["size_bytes"]),
            duration_secs=float(r["duration_secs"]) if r["duration_secs"] is not None else None,
            recorded_at=r["recorded_at"],
            ingested_at=r["ingested_at"],
        )


def archive_dir_for(recorded_at: datetime, sha256: str, ext: str) -> Path:
    base = get_settings().archive_dir()
    year = recorded_at.strftime("%Y")
    day = recorded_at.strftime("%Y-%m-%d")
    slot = recorded_at.strftime("%H-%M") + "_" + short_hash(sha256)
    folder = base / year / day / slot
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def find_by_sha(sha256: str) -> Recording | None:
    row = get_conn().execute(
        "SELECT * FROM recordings WHERE sha256 = ?", (sha256,)
    ).fetchone()
    return Recording.from_row(row) if row else None


def find_by_archive_path(archive_path: Path) -> Recording | None:
    row = get_conn().execute(
        "SELECT * FROM recordings WHERE archive_path = ?",
        (str(archive_path),),
    ).fetchone()
    return Recording.from_row(row) if row else None


def insert_recording(
    sha256: str,
    src_path: Path,
    archive_path: Path,
    size_bytes: int,
    duration_secs: float | None,
    recorded_at: datetime | None,
) -> Recording:
    ingested_at = now_iso()
    recorded_at_iso = recorded_at.isoformat() if recorded_at else None
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO recordings(sha256, src_path, archive_path, size_bytes, duration_secs, recorded_at, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sha256,
                str(src_path),
                str(archive_path),
                size_bytes,
                duration_secs,
                recorded_at_iso,
                ingested_at,
            ),
        )
        rid = int(cur.lastrowid)
    return Recording(
        id=rid,
        sha256=sha256,
        src_path=src_path,
        archive_path=archive_path,
        size_bytes=size_bytes,
        duration_secs=duration_secs,
        recorded_at=recorded_at_iso,
        ingested_at=ingested_at,
    )


def insert_transcript(
    recording_id: int,
    txt_path: Path,
    srt_path: Path,
    md_path: Path,
    language: str | None,
    model: str,
    text: str,
) -> int:
    with transaction() as conn:
        # Replace any prior transcript for this recording.
        conn.execute("DELETE FROM transcripts WHERE recording_id = ?", (recording_id,))
        cur = conn.execute(
            "INSERT INTO transcripts(recording_id, txt_path, srt_path, md_path, language, model, transcribed_at, text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (recording_id, str(txt_path), str(srt_path), str(md_path),
             language, model, now_iso(), text),
        )
        return int(cur.lastrowid)


def insert_enrichment(
    recording_id: int,
    backend: str,
    task: str,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float | None,
    transcript_sha: str,
    output_text: str,
) -> int:
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO enrichments(recording_id, backend, task, model, input_tokens, output_tokens, cost_usd, created_at, transcript_sha, output_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (recording_id, backend, task, model, input_tokens, output_tokens,
             cost_usd, now_iso(), transcript_sha, output_text),
        )
        return int(cur.lastrowid)


@dataclass
class SearchHit:
    recording_id: int
    archive_path: Path
    md_path: Path
    snippet: str
    rank: float


def search(query: str, limit: int = 20) -> list[SearchHit]:
    """FTS5 search. Returns hits sorted by bm25 rank."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT t.recording_id AS rid, r.archive_path AS apath, t.md_path AS mpath, "
        "       snippet(transcripts_fts, 0, '[', ']', ' … ', 12) AS snip, "
        "       bm25(transcripts_fts) AS rank "
        "FROM transcripts_fts "
        "JOIN transcripts t ON t.id = transcripts_fts.rowid "
        "JOIN recordings r ON r.id = t.recording_id "
        "WHERE transcripts_fts MATCH ? "
        "ORDER BY rank LIMIT ?",
        (query, limit),
    ).fetchall()
    return [
        SearchHit(
            recording_id=int(r["rid"]),
            archive_path=Path(r["apath"]),
            md_path=Path(r["mpath"]),
            snippet=r["snip"],
            rank=float(r["rank"]),
        )
        for r in rows
    ]


def list_recordings(limit: int = 50) -> list[Recording]:
    rows = get_conn().execute(
        "SELECT * FROM recordings ORDER BY COALESCE(recorded_at, ingested_at) DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [Recording.from_row(r) for r in rows]


def get_transcript_text(recording_id: int) -> str | None:
    row = get_conn().execute(
        "SELECT text FROM transcripts WHERE recording_id = ?", (recording_id,)
    ).fetchone()
    return row["text"] if row else None


def recordings_with_transcripts(recording_ids: Iterable[int]) -> set[int]:
    """Return the subset of given recording_ids that already have a transcript row."""
    ids = list(recording_ids)
    if not ids:
        return set()
    placeholders = ",".join("?" * len(ids))
    rows = get_conn().execute(
        f"SELECT recording_id FROM transcripts WHERE recording_id IN ({placeholders})",
        ids,
    ).fetchall()
    return {int(r["recording_id"]) for r in rows}


def list_enrichments(recording_id: int, *, with_text: bool = True) -> list[dict]:
    """Past enrichments for a recording, newest first.

    `with_text=False` omits the (potentially large) output_text body — use it for
    listing tools and call get_enrichment_text(id) on demand.
    """
    cols = "id, backend, task, model, input_tokens, output_tokens, cost_usd, created_at"
    if with_text:
        cols += ", output_text"
    rows = get_conn().execute(
        f"SELECT {cols} FROM enrichments WHERE recording_id = ? ORDER BY created_at DESC",
        (recording_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = {
            "id": int(r["id"]),
            "backend": r["backend"],
            "task": r["task"],
            "model": r["model"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cost_usd": r["cost_usd"],
            "created_at": r["created_at"],
        }
        if with_text:
            d["output_text"] = r["output_text"]
        out.append(d)
    return out


def get_enrichment_text(enrichment_id: int) -> str | None:
    row = get_conn().execute(
        "SELECT output_text FROM enrichments WHERE id = ?", (enrichment_id,),
    ).fetchone()
    return row["output_text"] if row else None


def find_recording_for_folder(folder: Path) -> Recording | None:
    """Find the recording whose archive_path lives in this folder, regardless of audio extension."""
    row = get_conn().execute(
        "SELECT * FROM recordings WHERE archive_path LIKE ? LIMIT 1",
        (str(folder / "audio.%"),),
    ).fetchone()
    return Recording.from_row(row) if row else None


def append_enrichment_to_md(md_path: Path, result_text: str, backend: str, task: str) -> None:
    """Append a labeled enrichment block to a transcript .md."""
    block = (
        f"\n\n## Enrichment ({backend}, {task}, {now_iso()})\n\n"
        f"{result_text.strip()}\n"
    )
    with md_path.open("a", encoding="utf-8") as f:
        f.write(block)


def record_enrichment_for_folder(folder: Path, transcript: str, result) -> None:
    """Insert an enrichments row keyed to the recording in `folder`. No-op if not found."""
    rec = find_recording_for_folder(folder)
    if rec is None:
        return
    insert_enrichment(
        recording_id=rec.id,
        backend=result.backend,
        task=result.task,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        transcript_sha=text_sha256(transcript),
        output_text=result.text,
    )
