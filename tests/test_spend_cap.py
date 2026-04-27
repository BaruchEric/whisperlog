"""Spend cap enforcement."""

from __future__ import annotations

import pytest

from whisperlog.ledger import (
    SpendCapExceeded,
    assert_within_cap,
    daily_total_usd,
    estimate_cost_usd,
    record_spend,
)


def test_estimate_cost_sonnet():
    # 1000 input + 500 output for sonnet @ $3/$15 per 1M
    cost = estimate_cost_usd("claude-sonnet-4-6", 1000, 500)
    assert cost == pytest.approx((1000 / 1_000_000) * 3.00 + (500 / 1_000_000) * 15.00)


def test_estimate_cost_opus_higher():
    sonnet = estimate_cost_usd("claude-sonnet-4-6", 100_000, 1_000)
    opus = estimate_cost_usd("claude-opus-4-7", 100_000, 1_000)
    assert opus > sonnet * 4  # opus is 5x sonnet


def test_record_spend_accumulates():
    assert daily_total_usd() == 0.0
    record_spend("claude-api", "claude-sonnet-4-6", 1000, 500, 0.012)
    record_spend("claude-api", "claude-sonnet-4-6", 2000, 800, 0.018)
    assert daily_total_usd() == pytest.approx(0.030, abs=1e-9)


def test_cap_blocks_above_limit():
    # Cap is $1.00 from conftest. Push past it.
    record_spend("claude-api", "claude-sonnet-4-6", 0, 0, 0.95)
    assert_within_cap(0.04)  # 0.95 + 0.04 < 1.00, ok
    with pytest.raises(SpendCapExceeded):
        assert_within_cap(0.10)  # 0.95 + 0.10 > 1.00


def test_cap_passes_when_under():
    assert_within_cap(0.001)
