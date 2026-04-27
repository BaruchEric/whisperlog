"""Transcribe output shape test — patches faster-whisper to avoid loading a model."""

from __future__ import annotations

from pathlib import Path

from ux570_transcribe import transcribe as tx
from ux570_transcribe.ingest import ingest_file
from ux570_transcribe.transcribe import (
    Segment,
    TranscriptionResult,
    transcribe_recording,
    write_outputs,
)


def _fake_result() -> TranscriptionResult:
    segs = [
        Segment(0.0, 1.0, "Hello world."),
        Segment(1.0, 2.5, "Second segment."),
    ]
    return TranscriptionResult(
        segments=segs,
        language="en",
        duration=2.5,
        text="Hello world.\nSecond segment.",
    )


def test_write_outputs_shape(tmp_path: Path, monkeypatch):
    src = tmp_path / "rec.mp3"
    src.write_bytes(b"ID3\x00\x00\x00fake")
    rec, _ = ingest_file(src)

    txt, srt, md = write_outputs(rec, _fake_result())
    assert txt.name == "transcript.txt"
    assert srt.name == "transcript.srt"
    assert md.name == "transcript.md"
    assert "Hello world." in txt.read_text()
    assert "00:00:00,000 --> 00:00:01,000" in srt.read_text()
    md_text = md.read_text()
    assert md_text.startswith("# Transcript:")
    assert "## Transcript" in md_text


def test_transcribe_recording_persists(tmp_path: Path, monkeypatch):
    src = tmp_path / "rec.mp3"
    src.write_bytes(b"ID3\x00\x00\x00fake")
    rec, _ = ingest_file(src)

    monkeypatch.setattr(tx, "transcribe_audio", lambda _path: _fake_result())
    txt, srt, md, result = transcribe_recording(rec)

    assert txt.exists() and srt.exists() and md.exists()
    from ux570_transcribe.archive import get_transcript_text
    assert "Hello world." in (get_transcript_text(rec.id) or "")
