"""Ingest audio recordings into the archive.

Default flow auto-detects a Sony ICD-UX570 mount:
    macOS: /Volumes/IC RECORDER (or "IC RECORDER 1" if duplicate names exist)
    Linux: /media/$USER/IC* or /run/media/$USER/IC*
    Sony layout: REC_FILE/FOLDER01..FOLDER05/*.MP3 or *.WAV

Generic mode: pass any directory to ingest_from_path() and it walks recursively.
If REC_FILE/ is present, the Sony layout is used; otherwise all common audio
files under the path are picked up.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .archive import (
    Recording,
    archive_dir_for,
    find_by_sha,
    insert_recording,
)
from .utils import file_sha256, safe_copy

logger = logging.getLogger("whisperlog.ingest")

DEVICE_NAME_HINT = "IC RECORDER"
RECORDING_DIRNAME = "REC_FILE"
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".mp4", ".flac", ".ogg", ".oga", ".aac", ".opus", ".webm"}


def detect_mount_point() -> Path | None:
    sys = platform.system()
    candidates: list[Path] = []
    if sys == "Darwin":
        candidates.extend(Path("/Volumes").glob("*"))
    elif sys == "Linux":
        user = os.environ.get("USER", "")
        for base in (Path(f"/media/{user}"), Path(f"/run/media/{user}"), Path("/mnt")):
            if base.exists():
                candidates.extend(base.glob("*"))
    for c in candidates:
        if not c.is_dir():
            continue
        if DEVICE_NAME_HINT in c.name.upper() and (c / RECORDING_DIRNAME).is_dir():
            return c
    # Fallback: any volume that has a REC_FILE dir.
    for c in candidates:
        if c.is_dir() and (c / RECORDING_DIRNAME).is_dir():
            return c
    return None


def list_device_recordings(mount: Path) -> list[Path]:
    """List audio files in the Sony REC_FILE/FOLDER01..05 layout. Returns [] if absent."""
    rec_root = mount / RECORDING_DIRNAME
    if not rec_root.is_dir():
        return []
    files: list[Path] = []
    for folder in sorted(rec_root.glob("FOLDER*")):
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.suffix.lower() in AUDIO_SUFFIXES:
                files.append(f)
    return files


def list_audio_files(root: Path, *, recursive: bool = True) -> list[Path]:
    """Find audio files under root. Uses Sony REC_FILE layout if present, else walks."""
    if not root.is_dir():
        return []
    if (root / RECORDING_DIRNAME).is_dir():
        return list_device_recordings(root)
    walker: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
    return sorted(
        f for f in walker if f.is_file() and f.suffix.lower() in AUDIO_SUFFIXES
    )


def ingest_file(src: Path) -> tuple[Recording, bool]:
    """Copy a single audio file into the archive. Returns (record, is_new)."""
    sha = file_sha256(src)
    existing = find_by_sha(sha)
    if existing is not None:
        logger.debug("Already ingested: %s -> %s", src, existing.archive_path)
        return existing, False

    st = src.stat()
    # Sony writes mtime to the recording end time. Good enough for archive bucketing.
    recorded_at = datetime.fromtimestamp(st.st_mtime).astimezone()
    folder = archive_dir_for(recorded_at, sha, src.suffix.lower())
    dest = folder / f"audio{src.suffix.lower()}"
    safe_copy(src, dest)
    rec = insert_recording(
        sha256=sha,
        src_path=src,
        archive_path=dest,
        size_bytes=st.st_size,
        duration_secs=None,
        recorded_at=recorded_at,
    )
    logger.info("Ingested: %s -> %s", src.name, dest)
    return rec, True


def ingest_from_path(source: Path) -> list[tuple[Recording, bool]]:
    """Ingest every audio file under source. Sony layout used if REC_FILE/ is present."""
    return [ingest_file(f) for f in list_audio_files(source)]


def partition_ingest(
    results: list[tuple[Recording, bool]],
) -> tuple[list[Recording], list[Recording]]:
    """Split ingest_from_path output into (new_recs, all_recs)."""
    new_recs = [rec for rec, is_new in results if is_new]
    all_recs = [rec for rec, _ in results]
    return new_recs, all_recs


def eject(mount: Path) -> bool:
    """Best-effort unmount. Returns True on success."""
    sys = platform.system()
    try:
        if sys == "Darwin":
            subprocess.run(["diskutil", "eject", str(mount)], check=True, capture_output=True)
            return True
        if sys == "Linux":
            subprocess.run(["umount", str(mount)], check=True, capture_output=True)
            return True
    except subprocess.CalledProcessError as e:
        logger.warning("Eject failed: %s", e.stderr.decode("utf-8", errors="replace"))
    return False
