"""Spend ledger backed by SQLite. Process-safe via BEGIN IMMEDIATE."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from .config import get_settings
from .db import get_conn, transaction
from .utils import now_iso

# Pricing in USD per 1M tokens. Update if Anthropic prices change.
# (input_per_mtok, output_per_mtok)
_CLAUDE_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (15.00, 75.00),
    "claude-opus-4-5": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}


def price_for_model(model: str) -> tuple[float, float]:
    if model in _CLAUDE_PRICING:
        return _CLAUDE_PRICING[model]
    for key, val in _CLAUDE_PRICING.items():
        if model.startswith(key):
            return val
    return (3.00, 15.00)  # sonnet-equivalent default


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = price_for_model(model)
    return round((input_tokens / 1_000_000) * inp + (output_tokens / 1_000_000) * out, 6)


@dataclass
class SpendSummary:
    day: str
    total_usd: float
    input_tokens: int
    output_tokens: int


def _today_iso() -> str:
    return date.today().isoformat()


def daily_total_usd(day: str | None = None) -> float:
    day = day or _today_iso()
    row = get_conn().execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) FROM spend WHERE day = ?",
        (day,),
    ).fetchone()
    return float(row[0])


def remaining_budget_usd() -> float:
    cap = get_settings().max_daily_claude_usd
    return max(0.0, cap - daily_total_usd())


def assert_within_cap(planned_cost_usd: float) -> None:
    """Raise if today's spend + planned would exceed the daily cap."""
    cap = get_settings().max_daily_claude_usd
    spent = daily_total_usd()
    if spent + planned_cost_usd > cap + 1e-9:
        raise SpendCapExceeded(
            f"Daily spend cap ${cap:.2f} would be exceeded "
            f"(spent ${spent:.4f}, this call ~${planned_cost_usd:.4f})."
        )


def record_spend(
    backend: str,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO spend(day, backend, model, input_tokens, output_tokens, cost_usd, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_today_iso(), backend, model, input_tokens, output_tokens, cost_usd, now_iso()),
        )


def summary_last_n_days(n: int) -> list[SpendSummary]:
    cutoff = (datetime.now(UTC).date() - timedelta(days=n - 1)).isoformat()
    rows = get_conn().execute(
        "SELECT day, "
        "COALESCE(SUM(cost_usd),0) AS total, "
        "COALESCE(SUM(input_tokens),0) AS itok, "
        "COALESCE(SUM(output_tokens),0) AS otok "
        "FROM spend WHERE day >= ? GROUP BY day ORDER BY day DESC",
        (cutoff,),
    ).fetchall()
    return [
        SpendSummary(day=r["day"], total_usd=float(r["total"]),
                     input_tokens=int(r["itok"]), output_tokens=int(r["otok"]))
        for r in rows
    ]


class SpendCapExceeded(RuntimeError):
    pass
