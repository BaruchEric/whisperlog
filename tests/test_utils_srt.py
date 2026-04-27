"""SRT formatting + JSONL audit log shape."""

from __future__ import annotations

import json
from pathlib import Path

from whisperlog.utils import (
    append_jsonl,
    file_sha256,
    srt_timestamp,
    text_sha256,
    write_srt,
)


def test_srt_timestamp_zero():
    assert srt_timestamp(0) == "00:00:00,000"


def test_srt_timestamp_basic():
    # 1h 2m 3.456s
    assert srt_timestamp(3723.456) == "01:02:03,456"


def test_srt_timestamp_rounds_milliseconds():
    # 0.0009s → 1ms
    assert srt_timestamp(0.0009) == "00:00:00,001"


def test_srt_timestamp_negative_clamped():
    assert srt_timestamp(-5) == "00:00:00,000"


def test_write_srt(tmp_path: Path):
    segs = [
        {"start": 0.0, "end": 1.5, "text": "Hello there."},
        {"start": 1.5, "end": 3.25, "text": "Second line."},
    ]
    dest = tmp_path / "x.srt"
    write_srt(segs, dest)
    content = dest.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,500\nHello there.\n" in content
    assert "2\n00:00:01,500 --> 00:00:03,250\nSecond line.\n" in content


def test_text_sha256_stable():
    assert text_sha256("abc") == text_sha256("abc")
    assert text_sha256("abc") != text_sha256("abd")


def test_file_sha256_matches_text_sha(tmp_path: Path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello world")
    assert len(file_sha256(p)) == 64


def test_append_jsonl(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    append_jsonl(p, {"a": 1})
    append_jsonl(p, {"b": 2})
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0]) == {"a": 1}
    assert json.loads(lines[1]) == {"b": 2}
