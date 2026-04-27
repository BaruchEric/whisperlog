"""Archive layout, lookup, and FTS5 search.

Layout:
    <archive_dir>/<YYYY>/<YYYY-MM-DD>/<HH-MM>_<sha8>/
        audio.<ext>
        transcript.txt
        transcript.srt
        transcript.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import get_settings
from .db import get_conn, transaction
from .utils import now_iso, short_hash


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
) -> int:
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
                recorded_at.isoformat() if recorded_at else None,
                now_iso(),
            ),
        )
        return int(cur.lastrowid)


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
