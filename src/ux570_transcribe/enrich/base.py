"""Enricher abstract base + prompt template loader + audit logging.

Audit log policy: never write transcript content. Only sha256 + first 80 chars +
token counts + cost, per the privacy spec.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..config import get_settings
from ..utils import append_jsonl, now_iso, text_sha256

logger = logging.getLogger("ux570.enrich")

Backend = Literal["ollama", "claude-api", "claude-cli"]

PROMPT_PLACEHOLDER = "{{transcript}}"


@dataclass
class EnrichResult:
    text: str
    backend: Backend
    task: str
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    extras: dict = field(default_factory=dict)


def _prompts_dir() -> Path:
    """Resolve the prompts/ directory next to the installed package or repo root."""
    pkg_root = Path(__file__).resolve().parent.parent
    # Repo layout: src/ux570_transcribe/enrich/base.py -> repo/prompts
    repo_root = pkg_root.parent.parent
    candidates = [pkg_root / "prompts", repo_root / "prompts"]
    for c in candidates:
        if c.is_dir():
            return c
    return repo_root / "prompts"


def load_prompt_template(task: str) -> str:
    """Load prompts/<task>.md. Tasks may be aliased with hyphens or underscores."""
    pd = _prompts_dir()
    candidates = [
        pd / f"{task}.md",
        pd / f"{task.replace('-', '_')}.md",
        pd / f"{task.replace('_', '-')}.md",
    ]
    for c in candidates:
        if c.is_file():
            return c.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"No prompt template for task '{task}'. Looked in: {pd}. "
        f"Available: {[p.name for p in pd.glob('*.md')] if pd.is_dir() else '(no dir)'}"
    )


def render_prompt(template: str, transcript: str) -> str:
    if PROMPT_PLACEHOLDER not in template:
        # Allow templates that don't use the placeholder — append transcript at the end.
        return template.rstrip() + "\n\n---\n\n" + transcript
    return template.replace(PROMPT_PLACEHOLDER, transcript)


def audit_cloud_call(
    backend: Backend,
    task: str,
    model: str | None,
    transcript: str,
    transcript_path: Path | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    """Append an audit-log record. Never includes transcript content — only a hash and a tiny preview."""
    rec = {
        "ts": now_iso(),
        "backend": backend,
        "task": task,
        "model": model,
        "transcript_sha256": text_sha256(transcript),
        "transcript_chars": len(transcript),
        "transcript_preview": transcript[:80].replace("\n", " "),
        "transcript_path": str(transcript_path) if transcript_path else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
    }
    append_jsonl(get_settings().audit_log_path(), rec)


def log_enrich_call(
    backend: Backend,
    task: str,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    rec = {
        "ts": now_iso(),
        "backend": backend,
        "task": task,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
    }
    append_jsonl(get_settings().enrich_log_path(), rec)


class Enricher(ABC):
    backend: Backend

    @abstractmethod
    def enrich(self, transcript: str, prompt: str, *, task: str, **kwargs) -> EnrichResult:
        """Send (transcript, prompt) to the backend; return an EnrichResult."""


def get_enricher(backend: Backend) -> Enricher:
    if backend == "ollama":
        from .ollama import OllamaEnricher
        return OllamaEnricher()
    if backend == "claude-api":
        from .claude_api import ClaudeAPIEnricher
        return ClaudeAPIEnricher()
    if backend == "claude-cli":
        from .claude_cli import ClaudeCLIEnricher
        return ClaudeCLIEnricher()
    raise ValueError(f"Unknown enrichment backend: {backend}")
