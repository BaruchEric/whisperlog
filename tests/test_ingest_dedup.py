"""Ingest dedup: same file ingested twice → second call returns existing record."""

from __future__ import annotations

from pathlib import Path

from whisperlog.ingest import ingest_file, ingest_from_path, list_audio_files


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


def test_list_audio_files_walks_generic_directory(tmp_path: Path):
    src = tmp_path / "drive"
    (src / "voice").mkdir(parents=True)
    (src / "music").mkdir()
    a = src / "voice" / "memo1.m4a"
    b = src / "music" / "song.flac"
    c = src / "voice" / "memo2.MP3"
    notes = src / "notes.txt"
    a.write_bytes(b"a"); b.write_bytes(b"b"); c.write_bytes(b"c"); notes.write_text("x")

    found = list_audio_files(src)
    assert set(found) == {a, b, c}
    assert notes not in found


def test_list_audio_files_uses_sony_layout_when_present(tmp_path: Path):
    mount = tmp_path / "mount"
    rec_root = mount / "REC_FILE" / "FOLDER01"
    rec_root.mkdir(parents=True)
    (rec_root / "240101_001.MP3").write_bytes(b"sony")
    # Stray audio outside REC_FILE must NOT be returned in Sony mode.
    (mount / "ignore_me.mp3").write_bytes(b"x")

    found = list_audio_files(mount)
    assert len(found) == 1
    assert found[0].name == "240101_001.MP3"


def test_ingest_from_path_picks_up_generic_dir(tmp_path: Path):
    src = tmp_path / "uploads"
    nested = src / "nested"
    nested.mkdir(parents=True)
    _fake_audio(src / "first.mp3")
    (nested / "second.mp3").write_bytes(b"ID3\x00\x00\x00different-payload")

    results = ingest_from_path(src)
    assert len(results) == 2
    assert all(is_new for _, is_new in results)
    assert {r.archive_path.name for r, _ in results} == {"audio.mp3"}
