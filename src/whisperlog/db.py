"""SQLite-backed archive index, FTS5 search, and spend ledger.

Single-user CLI: one DB file at ~/.whisperlog/index.db. WAL mode, foreign keys on.
All writes go through this module so concurrent CLI invocations stay consistent.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import get_settings

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS recordings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256          TEXT NOT NULL UNIQUE,
    src_path        TEXT NOT NULL,
    archive_path    TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    duration_secs   REAL,
    recorded_at     TEXT,
    ingested_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id    INTEGER NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
    txt_path        TEXT NOT NULL,
    srt_path        TEXT NOT NULL,
    md_path         TEXT NOT NULL,
    language        TEXT,
    model           TEXT NOT NULL,
    transcribed_at  TEXT NOT NULL,
    text            TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    text,
    content='transcripts',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
    INSERT INTO transcripts_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS transcripts_au AFTER UPDATE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO transcripts_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS enrichments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id    INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    backend         TEXT NOT NULL,
    task            TEXT NOT NULL,
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    created_at      TEXT NOT NULL,
    transcript_sha  TEXT NOT NULL,
    output_text     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spend (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    day             TEXT NOT NULL,
    backend         TEXT NOT NULL,
    model           TEXT,
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER NOT NULL,
    cost_usd        REAL NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS spend_day_idx ON spend(day);
"""


_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_db_path: Path | None = None


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def get_conn() -> sqlite3.Connection:
    global _conn, _db_path
    settings = get_settings()
    target = settings.db_path()
    with _lock:
        if _conn is None or _db_path != target:
            if _conn is not None:
                _conn.close()
            _conn = _connect(target)
            _db_path = target
        return _conn


def close() -> None:
    global _conn, _db_path
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
            _db_path = None


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    with _lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
