"""Configuration loaded from .env via pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _expand(p: str | Path) -> Path:
    return Path(p).expanduser().resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core paths
    whisperlog_archive_dir: Path = Field(default=Path("~/Documents/whisperlog-archive"))
    whisperlog_state_dir: Path = Field(default=Path("~/.whisperlog"))

    # Whisper
    whisper_model: str = "small.en"
    whisper_device: Literal["auto", "cpu", "cuda", "mps"] = "auto"
    whisper_compute_type: str = "int8"
    enable_vad: bool = True
    whisper_language: str | None = "en"

    # Concurrency
    max_concurrent_transcriptions: int = 1

    # Enrichment
    default_enrich_backend: Literal["ollama", "claude-api", "claude-cli"] = "ollama"
    default_enrich_task: str = "summarize"

    # Ollama
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_secs: int = 180

    # Claude API
    claude_model: str = "claude-sonnet-4-6"
    claude_agent_model: str = "claude-opus-4-7"
    claude_fallback_model: str = "claude-sonnet-4-6"
    claude_max_tokens: int = 4096
    max_daily_claude_usd: float = 5.00
    cost_confirm_usd: float = 0.10

    # Claude CLI
    claude_cli_path: str = "claude"

    @field_validator("whisperlog_archive_dir", "whisperlog_state_dir", mode="before")
    @classmethod
    def _expand_paths(cls, v: str | Path) -> Path:
        return _expand(v)

    def state_dir(self) -> Path:
        self.whisperlog_state_dir.mkdir(parents=True, exist_ok=True)
        return self.whisperlog_state_dir

    def archive_dir(self) -> Path:
        self.whisperlog_archive_dir.mkdir(parents=True, exist_ok=True)
        return self.whisperlog_archive_dir

    def db_path(self) -> Path:
        return self.state_dir() / "index.db"

    def audit_log_path(self) -> Path:
        return self.state_dir() / "audit.log"

    def enrich_log_path(self) -> Path:
        return self.state_dir() / "enrich.log"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_for_tests() -> None:
    global _settings
    _settings = None
