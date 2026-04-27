"""Pytest fixtures: isolate state and archive dirs per test."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_dirs(tmp_path: Path, monkeypatch):
    """Point WHISPERLOG_ARCHIVE_DIR and WHISPERLOG_STATE_DIR at tmp dirs and reset settings."""
    monkeypatch.setenv("WHISPERLOG_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("WHISPERLOG_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MAX_DAILY_CLAUDE_USD", "1.00")
    monkeypatch.setenv("COST_CONFIRM_USD", "0.10")

    from whisperlog import config as cfg
    from whisperlog import db

    cfg.reset_settings_for_tests()
    db.close()
    yield
    db.close()
    cfg.reset_settings_for_tests()
