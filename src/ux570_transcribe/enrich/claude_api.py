"""Claude API enricher with cost guards and audit logging.

API key comes from the OS keychain. Never read from .env. Never logged.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ..config import get_settings
from ..ledger import (
    SpendCapExceeded,
    assert_within_cap,
    estimate_cost_usd,
    estimate_input_cost_usd,
    record_spend,
)
from ..secrets import require_anthropic_key
from .base import (
    Backend,
    Enricher,
    EnrichResult,
    audit_cloud_call,
    log_enrich_call,
)

logger = logging.getLogger("ux570.enrich.claude_api")


class ConfirmationDeclined(RuntimeError):
    pass


class ClaudeAPIEnricher(Enricher):
    backend: Backend = "claude-api"

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def _client(self):
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic SDK is not installed. Install: `uv pip install -e '.[cloud]'`"
            ) from e
        return anthropic.Anthropic(api_key=require_anthropic_key())

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
        retries: int = 3,
        **_,
    ) -> EnrichResult:
        s = get_settings()
        chosen_model = model or self.model or s.claude_model
        max_out = max_tokens or s.claude_max_tokens

        client = self._client()

        # 1. Estimate input tokens via the SDK's count_tokens (avoids an unmeasured call).
        try:
            count = client.messages.count_tokens(
                model=chosen_model,
                messages=[{"role": "user", "content": prompt}],
            )
            est_in = int(getattr(count, "input_tokens", 0) or 0)
        except Exception as e:
            logger.warning("count_tokens failed (%s); estimating from char length", e)
            est_in = max(1, len(prompt) // 4)

        est_cost = estimate_input_cost_usd(chosen_model, est_in, max_out)
        logger.info(
            "Claude API: model=%s task=%s est_input=%d max_output=%d est_cost=$%.4f",
            chosen_model, task, est_in, max_out, est_cost,
        )

        # 2. Spend cap check.
        if not skip_cap_check:
            assert_within_cap(est_cost)

        # 3. Cost confirmation prompt for non-trivial calls.
        if confirm and est_cost > s.cost_confirm_usd:
            self._require_confirmation(est_in, est_cost, chosen_model, task)

        # 4. Send with retry on transient errors.
        try:
            import anthropic
        except ImportError:
            anthropic = None  # type: ignore

        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                response = client.messages.create(
                    model=chosen_model,
                    max_tokens=max_out,
                    messages=[{"role": "user", "content": prompt}],
                )
                break
            except Exception as e:
                transient = False
                if anthropic is not None:
                    transient = isinstance(
                        e,
                        (
                            getattr(anthropic, "RateLimitError", Exception),
                            getattr(anthropic, "APIConnectionError", Exception),
                            getattr(anthropic, "APITimeoutError", Exception),
                            getattr(anthropic, "InternalServerError", Exception),
                        ),
                    )
                if not transient or attempt == retries - 1:
                    last_err = e
                    raise
                wait = (2 ** attempt) + 0.5
                logger.warning("Transient Claude error (%s); retry %d in %.1fs", e, attempt + 1, wait)
                time.sleep(wait)
        else:
            assert last_err is not None
            raise last_err

        # 5. Extract text and usage.
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        actual_cost = estimate_cost_usd(chosen_model, in_tok, out_tok)

        record_spend(self.backend, chosen_model, in_tok, out_tok, actual_cost)
        audit_cloud_call(
            self.backend, task, chosen_model, transcript, transcript_path,
            in_tok, out_tok, actual_cost,
        )
        log_enrich_call(self.backend, task, chosen_model, in_tok, out_tok, actual_cost)

        logger.info(
            "Claude API done: in=%d out=%d cost=$%.4f", in_tok, out_tok, actual_cost,
        )

        return EnrichResult(
            text=text,
            backend=self.backend,
            task=task,
            model=chosen_model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=actual_cost,
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
