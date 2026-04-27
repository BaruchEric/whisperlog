"""Ollama HTTP enricher. No tokens, no cost, no network beyond localhost."""

from __future__ import annotations

import logging

import httpx

from ..config import get_settings
from .base import Backend, Enricher, EnrichResult, log_enrich_call

logger = logging.getLogger("whisperlog.enrich.ollama")


class OllamaEnricher(Enricher):
    backend: Backend = "ollama"

    def enrich(self, transcript: str, prompt: str, *, task: str, **kwargs) -> EnrichResult:
        s = get_settings()
        url = s.ollama_host.rstrip("/") + "/api/generate"
        payload = {
            "model": kwargs.get("model") or s.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.2),
                "num_ctx": kwargs.get("num_ctx", 8192),
            },
        }
        logger.debug("POST %s model=%s", url, payload["model"])
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

        log_enrich_call(self.backend, task, payload["model"], input_tokens, output_tokens, 0.0)

        return EnrichResult(
            text=text,
            backend=self.backend,
            task=task,
            model=payload["model"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=0.0,
            extras={"raw": data},
        )
