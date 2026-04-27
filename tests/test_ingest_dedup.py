"""Ingest dedup: same file ingested twice → second call returns existing record."""

from __future__ import annotations

from pathlib import Path

from ux570_transcribe.ingest import ingest_file


def _fake_audio(p: Path) -> Path:
    p.write_bytes(b"ID3\x00\x00\x00fake-mp3-bytes-deadbeef")
    return p


def test_ingest_file_dedup(tmp_path: Path):
    src = _fake_audio(tmp_path / "rec1.mp3")
    rec1, new1 = ingest_file(src)
    assert new1 is True
    assert rec1.archive_path.exists()

    rec2, new2 = ingest_file(src)
    assert new2 is False
    assert rec2.id == rec1.id
    assert rec2.archive_path == rec1.archive_path


def test_ingest_different_files(tmp_path: Path):
    a = _fake_audio(tmp_path / "a.mp3")
    b = (tmp_path / "b.mp3")
    b.write_bytes(b"ID3\x00\x00\x00different-bytes-cafebabe")

    ra, _ = ingest_file(a)
    rb, _ = ingest_file(b)
    assert ra.sha256 != rb.sha256
    assert ra.archive_path != rb.archive_path
