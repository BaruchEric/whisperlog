"""faster-whisper wrapper with VAD and Sony-recorder-friendly defaults."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .archive import Recording, insert_transcript
from .config import get_settings
from .utils import write_srt

logger = logging.getLogger("ux570.transcribe")

_model = None
_model_key: tuple[str, str, str] | None = None


def _get_model():
    global _model, _model_key
    s = get_settings()
    key = (s.whisper_model, s.whisper_device, s.whisper_compute_type)
    if _model is not None and _model_key == key:
        return _model
    from faster_whisper import WhisperModel  # heavy import; defer until needed

    device = s.whisper_device
    if device == "auto":
        device = "auto"  # faster-whisper accepts "auto" directly
    logger.info("Loading Whisper model %s (device=%s, compute=%s)",
                s.whisper_model, device, s.whisper_compute_type)
    _model = WhisperModel(
        s.whisper_model,
        device=device,
        compute_type=s.whisper_compute_type,
    )
    _model_key = key
    return _model


@dataclass
class Segment:
    start: float
    end: float
    text: str

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text}


@dataclass
class TranscriptionResult:
    segments: list[Segment]
    language: str | None
    duration: float
    text: str


def transcribe_audio(audio_path: Path) -> TranscriptionResult:
    s = get_settings()
    model = _get_model()
    logger.info("Transcribing %s", audio_path)
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=s.whisper_language,
        vad_filter=s.enable_vad,
        # Avoid cascade hallucination on long silences typical of Sony recordings.
        condition_on_previous_text=False,
        beam_size=5,
    )
    segs: list[Segment] = []
    for seg in segments_iter:
        segs.append(Segment(start=float(seg.start), end=float(seg.end), text=seg.text))
    full_text = "\n".join(s.text.strip() for s in segs).strip()
    return TranscriptionResult(
        segments=segs,
        language=info.language,
        duration=float(info.duration),
        text=full_text,
    )


def write_outputs(rec: Recording, result: TranscriptionResult) -> tuple[Path, Path, Path]:
    folder = rec.archive_path.parent
    txt = folder / "transcript.txt"
    srt = folder / "transcript.srt"
    md = folder / "transcript.md"

    txt.write_text(result.text + "\n", encoding="utf-8")
    write_srt([s.as_dict() for s in result.segments], srt)

    header = (
        f"# Transcript: {rec.archive_path.name}\n\n"
        f"- **Recorded:** {rec.recorded_at or 'unknown'}\n"
        f"- **Source:** `{rec.src_path}`\n"
        f"- **Duration:** {result.duration:.1f}s\n"
        f"- **Language:** {result.language or '?'}\n"
        f"- **Whisper model:** {get_settings().whisper_model}\n\n"
        "## Transcript\n\n"
    )
    md.write_text(header + result.text + "\n", encoding="utf-8")
    return txt, srt, md


def transcribe_recording(rec: Recording) -> tuple[Path, Path, Path, TranscriptionResult]:
    result = transcribe_audio(rec.archive_path)
    txt, srt, md = write_outputs(rec, result)
    insert_transcript(
        recording_id=rec.id,
        txt_path=txt,
        srt_path=srt,
        md_path=md,
        language=result.language,
        model=get_settings().whisper_model,
        text=result.text,
    )
    return txt, srt, md, result


def transcribe_path(audio_path: Path) -> TranscriptionResult:
    """Standalone transcribe — does not enter the archive. For ad-hoc files."""
    return transcribe_audio(audio_path)


def iter_pending(recordings: Iterable[Recording]) -> Iterable[Recording]:
    """Filter recordings that have no transcript yet."""
    from .db import get_conn
    conn = get_conn()
    for rec in recordings:
        row = conn.execute(
            "SELECT 1 FROM transcripts WHERE recording_id = ?", (rec.id,)
        ).fetchone()
        if not row:
            yield rec
