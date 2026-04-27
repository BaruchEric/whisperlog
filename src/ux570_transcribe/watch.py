"""Watch daemon: poll for the UX570, ingest, transcribe, optionally enrich."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .archive import Recording, append_enrichment_to_md, record_enrichment_for_folder
from .config import get_settings
from .enrich import get_enricher, load_prompt_template, render_prompt
from .ingest import detect_mount_point, eject, ingest_from_path, list_audio_files
from .transcribe import iter_pending, transcribe_recording

logger = logging.getLogger("ux570.watch")


def _source_signature(source: Path) -> tuple:
    """Cheap fingerprint of a directory's audio files: (path, mtime_ns, size)."""
    out = []
    for f in list_audio_files(source):
        try:
            st = f.stat()
        except OSError:
            continue
        out.append((str(f), st.st_mtime_ns, st.st_size))
    return tuple(out)


def _process_pending(recordings: list[Recording], enrich: bool) -> None:
    s = get_settings()
    pending = list(iter_pending(recordings))
    logger.info("Pending transcription: %d / %d", len(pending), len(recordings))
    for rec in pending:
        try:
            _txt, _srt, md, result = transcribe_recording(rec)
            logger.info("Transcribed %s -> %s", rec.archive_path.name, md)
            if enrich:
                _safe_enrich(result.text, s.default_enrich_backend, s.default_enrich_task, md)
        except Exception as e:
            logger.exception("Transcription failed for %s: %s", rec.archive_path, e)


def _safe_enrich(transcript: str, backend: str, task: str, md_path: Path) -> None:
    try:
        enricher = get_enricher(backend)  # type: ignore[arg-type]
        template = load_prompt_template(task)
        prompt = render_prompt(template, transcript)
        result = enricher.enrich(transcript, prompt, task=task)
        append_enrichment_to_md(md_path, result.text, result.backend, task)
        record_enrichment_for_folder(md_path.parent, transcript, result)
    except Exception as e:
        logger.warning("Enrichment skipped: %s", e)


def watch_loop(
    *,
    poll_secs: float = 3.0,
    enrich: bool = False,
    eject_after: bool = True,
    once: bool = False,
    source: Path | None = None,
) -> None:
    """Poll for new recordings. Default: UX570 mount. With source: any folder."""
    if source is not None:
        source = source.expanduser().resolve()
        _watch_source(source, poll_secs=poll_secs, enrich=enrich, once=once)
        return

    seen_mount: Path | None = None
    while True:
        mount = detect_mount_point()
        if mount and mount != seen_mount:
            logger.info("Detected UX570 at %s", mount)
            results = ingest_from_path(mount)
            new_recs = [rec for rec, is_new in results if is_new]
            all_recs = [rec for rec, _ in results]
            logger.info("Ingested %d new (of %d total)", len(new_recs), len(all_recs))
            _process_pending(all_recs, enrich=enrich)
            if eject_after and eject(mount):
                logger.info("Ejected %s", mount)
            seen_mount = mount
        elif mount is None:
            seen_mount = None

        if once:
            return
        time.sleep(poll_secs)


def _watch_source(source: Path, *, poll_secs: float, enrich: bool, once: bool) -> None:
    """Watch a static directory. Re-scans only when (path,mtime,size) signature changes."""
    if not source.is_dir():
        logger.error("Source is not a directory: %s", source)
        return
    logger.info("Watching %s for new audio files", source)
    last_sig: tuple | None = None
    while True:
        sig = _source_signature(source)
        if sig != last_sig:
            results = ingest_from_path(source)
            new_recs = [rec for rec, is_new in results if is_new]
            all_recs = [rec for rec, _ in results]
            if new_recs:
                logger.info("Ingested %d new (of %d total)", len(new_recs), len(all_recs))
            _process_pending(all_recs, enrich=enrich)
            last_sig = sig

        if once:
            return
        time.sleep(poll_secs)
