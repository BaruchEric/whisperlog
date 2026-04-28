"""Transcribe output shape test — patches faster-whisper to avoid loading a model."""

from __future__ import annotations

from whisperlog import transcribe as tx
from whisperlog.ingest import ingest_file
from whisperlog.transcribe import (
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


def test_write_outputs_shape(fake_audio):
    rec, _ = ingest_file(fake_audio())

    txt, srt, md = write_outputs(rec, _fake_result(), model_name="small.en")
    assert txt.name == "transcript.txt"
    assert srt.name == "transcript.srt"
    assert md.name == "transcript.md"
    assert "Hello world." in txt.read_text()
    assert "00:00:00,000 --> 00:00:01,000" in srt.read_text()
    md_text = md.read_text()
    assert md_text.startswith("# Transcript:")
    assert "## Transcript" in md_text


def test_transcribe_recording_persists(fake_audio, monkeypatch):
    rec, _ = ingest_file(fake_audio())

    monkeypatch.setattr(tx, "transcribe_audio", lambda _path: _fake_result())
    txt, srt, md, result = transcribe_recording(rec)

    assert txt.exists() and srt.exists() and md.exists()
    from whisperlog.archive import get_transcript_text
    assert "Hello world." in (get_transcript_text(rec.id) or "")
