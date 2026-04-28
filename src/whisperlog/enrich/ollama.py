"""Ollama HTTP enricher. No tokens, no cost, no network beyond localhost."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from ..config import get_settings
from .base import Backend, Enricher, EnrichResult

logger = logging.getLogger(__name__)


class OllamaEnricher(Enricher):
    backend: Backend = "ollama"

    def enrich(
        self,
        transcript: str,
        prompt: str,
        *,
        task: str,
        transcript_path: Path | None = None,
        **kwargs,
    ) -> EnrichResult:
        s = get_settings()
        url = s.ollama_host.rstrip("/") + "/api/generate"
        model = kwargs.get("model") or s.ollama_model
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.2),
                "num_ctx": kwargs.get("num_ctx", 8192),
            },
        }
        logger.debug("POST %s model=%s", url, model)
        try:
            with httpx.Client(timeout=s.ollama_timeout_secs) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise RuntimeError(
                f"Ollama call failed: {e}. "
                f"Is Ollama running at {s.ollama_host}? Try `ollama serve`."
            ) from e

        text = (data.get("response") or "").strip()
        # Ollama returns these counts when available; treat as best-effort metadata.
        input_tokens = int(data.get("prompt_eval_count") or 0)
        output_tokens = int(data.get("eval_count") or 0)

        # Don't carry the full Ollama response (which echoes the prompt) into extras.
        extras = {
            k: data[k] for k in ("eval_duration", "load_duration", "total_duration") if k in data
        }

        return self._finalize(
            transcript=transcript,
            transcript_path=transcript_path,
            task=task,
            model=model,
            text=text,
            in_tok=input_tokens,
            out_tok=output_tokens,
            cost=0.0,
            extras=extras,
        )
