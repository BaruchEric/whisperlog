"""Claude API enricher with cost guards and audit logging.

API key comes from the OS keychain. Never read from .env. Never logged.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import get_settings
from ..ledger import (
    SpendCapExceeded,
    assert_within_cap,
    estimate_cost_usd,
    record_spend,
)
from ..secrets import require_anthropic_key
from ..utils import require_optional
from .base import Backend, Enricher, EnrichResult

logger = logging.getLogger(__name__)


class ConfirmationDeclined(RuntimeError):
    pass


class ClaudeAPIEnricher(Enricher):
    backend: Backend = "claude-api"

    def __init__(self, model: str | None = None) -> None:
        self.model = model
        self._cached_client = None

    def _client(self):
        if self._cached_client is None:
            anthropic = require_optional("anthropic", "cloud")
            # Let the SDK handle transient-error retries instead of a hand-rolled loop.
            self._cached_client = anthropic.Anthropic(
                api_key=require_anthropic_key(), max_retries=3,
            )
        return self._cached_client

    def enrich(
        self,
        transcript: str,
        prompt: str,
        *,
        task: str,
        model: str | None = None,
        max_tokens: int | None = None,
        confirm: bool = True,
        transcript_path: Path | None = None,
        skip_cap_check: bool = False,
        **_,
    ) -> EnrichResult:
        s = get_settings()
        chosen_model = model or self.model or s.claude_model
        max_out = max_tokens or s.claude_max_tokens

        client = self._client()

        try:
            count = client.messages.count_tokens(
                model=chosen_model,
                messages=[{"role": "user", "content": prompt}],
            )
            est_in = int(getattr(count, "input_tokens", 0) or 0)
        except Exception as e:
            logger.warning("count_tokens failed (%s); estimating from char length", e)
            est_in = max(1, len(prompt) // 4)

        est_cost = estimate_cost_usd(chosen_model, est_in, max_out)
        logger.info(
            "Claude API: model=%s task=%s est_input=%d max_output=%d est_cost=$%.4f",
            chosen_model, task, est_in, max_out, est_cost,
        )

        if not skip_cap_check:
            assert_within_cap(est_cost)

        if confirm and est_cost > s.cost_confirm_usd:
            self._require_confirmation(est_in, est_cost, chosen_model, task)

        response = client.messages.create(
            model=chosen_model,
            max_tokens=max_out,
            messages=[{"role": "user", "content": prompt}],
        )

        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        actual_cost = estimate_cost_usd(chosen_model, in_tok, out_tok)

        record_spend(self.backend, chosen_model, in_tok, out_tok, actual_cost)
        logger.info(
            "Claude API done: in=%d out=%d cost=$%.4f", in_tok, out_tok, actual_cost,
        )

        return self._finalize(
            transcript=transcript,
            transcript_path=transcript_path,
            task=task,
            model=chosen_model,
            text=text,
            in_tok=in_tok,
            out_tok=out_tok,
            cost=actual_cost,
            extras={"stop_reason": getattr(response, "stop_reason", None)},
        )

    def _require_confirmation(
        self, est_in: int, est_cost: float, model: str, task: str,
    ) -> None:
        from ..ledger import daily_total_usd

        cap = get_settings().max_daily_claude_usd
        spent = daily_total_usd()
        msg = (
            f"\nClaude API call ready:\n"
            f"  Task:           {task}\n"
            f"  Model:          {model}\n"
            f"  Input tokens:   {est_in:,}\n"
            f"  Est. cost:      ${est_cost:.4f}\n"
            f"  Spent today:    ${spent:.4f} / cap ${cap:.2f}\n"
            f"\nProceed? [y/N] "
        )
        ans = input(msg).strip().lower()
        if ans not in ("y", "yes"):
            raise ConfirmationDeclined("User declined Claude API call.")


__all__ = ["ClaudeAPIEnricher", "ConfirmationDeclined", "SpendCapExceeded"]
