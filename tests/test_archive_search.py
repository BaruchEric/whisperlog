"""FTS5 search smoke test."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ux570_transcribe.archive import insert_recording, insert_transcript, search


def _make_rec(tmp_path: Path, name: str, sha: str) -> int:
    archive_path = tmp_path / "archive" / name
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(b"fake")
    return insert_recording(
        sha256=sha,
        src_path=archive_path,
        archive_path=archive_path,
        size_bytes=4,
        duration_secs=None,
        recorded_at=datetime.now(),
    ).id


def test_fts_search(tmp_path: Path):
    rid_a = _make_rec(tmp_path, "a.mp3", "a" * 64)
    rid_b = _make_rec(tmp_path, "b.mp3", "b" * 64)

    insert_transcript(
        recording_id=rid_a,
        txt_path=tmp_path / "a.txt",
        srt_path=tmp_path / "a.srt",
        md_path=tmp_path / "a.md",
        language="en",
        model="small.en",
        text="The quick brown fox jumps over the lazy dog.",
    )
    insert_transcript(
        recording_id=rid_b,
        txt_path=tmp_path / "b.txt",
        srt_path=tmp_path / "b.srt",
        md_path=tmp_path / "b.md",
        language="en",
        model="small.en",
        text="A discussion about deployment pipelines and testing.",
    )

    hits = search("fox")
    assert len(hits) == 1
    assert hits[0].recording_id == rid_a

    hits = search("deployment OR pipelines")
    assert len(hits) == 1
    assert hits[0].recording_id == rid_b
