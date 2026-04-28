"""Helpers: hashing, timestamps, SRT formatting, audit logging."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("whisperlog")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def text_sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def srt_timestamp(seconds: float) -> str:
    """Format a timestamp for SRT: HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600 * 1000)
    m, ms = divmod(ms, 60 * 1000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: list[dict], dest: Path) -> None:
    """segments: [{'start': float, 'end': float, 'text': str}]"""
    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{srt_timestamp(seg['start'])} --> {srt_timestamp(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    dest.write_text("\n".join(lines), encoding="utf-8")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def safe_copy(src: Path, dst: Path) -> None:
    """Copy preserving mtime; create parents; never overwrite an existing file."""
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    # Avoid shutil.copy2: it calls chflags, which macOS denies in ~/Documents
    # without Full Disk Access. We only need mtime preserved.
    try:
        shutil.copyfile(src, tmp)
        st = src.stat()
        os.utime(tmp, (st.st_atime, st.st_mtime))
        tmp.rename(dst)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def short_hash(s: str, n: int = 8) -> str:
    return s[:n]


def require_optional(module: str, extra: str):
    """Import an optional dependency or raise a uniform install hint.

    `extra` is the pyproject extras name (e.g. "cloud", "agent", "mcp").
    """
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise RuntimeError(
            f"{module} is not installed. Install: `uv pip install -e '.[{extra}]'`"
        ) from e
