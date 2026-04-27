"""Enricher backend switching with mocked clients."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from whisperlog.enrich import get_enricher, render_prompt
from whisperlog.enrich.base import PROMPT_PLACEHOLDER


def test_get_enricher_unknown():
    with pytest.raises(ValueError):
        get_enricher("nope")  # type: ignore[arg-type]


def test_render_prompt_substitutes():
    tpl = "Summarize this:\n\n" + PROMPT_PLACEHOLDER
    out = render_prompt(tpl, "BODY")
    assert PROMPT_PLACEHOLDER not in out
    assert out.endswith("BODY")


def test_render_prompt_appends_when_no_placeholder():
    out = render_prompt("just instructions", "BODY")
    assert "BODY" in out
    assert "---" in out


def test_ollama_backend(monkeypatch):
    enricher = get_enricher("ollama")

    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "response": "  summary text  ",
        "prompt_eval_count": 100,
        "eval_count": 30,
    }
    fake_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as ctor:
        client_inst = ctor.return_value.__enter__.return_value
        client_inst.post.return_value = fake_resp

        result = enricher.enrich("hi", "PROMPT", task="summarize")

    assert result.text == "summary text"
    assert result.backend == "ollama"
    assert result.input_tokens == 100
    assert result.output_tokens == 30
    assert result.cost_usd == 0.0


def test_claude_api_backend_routes_through_sdk(monkeypatch):
    """Verify the API enricher sends through anthropic SDK and records spend."""
    monkeypatch.setattr(
        "whisperlog.secrets.require_anthropic_key",
        lambda: "sk-ant-test",
    )

    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(type="text", text="ok")]
    fake_msg.usage = MagicMock(input_tokens=10, output_tokens=5)
    fake_msg.stop_reason = "end_turn"

    fake_count = MagicMock(input_tokens=10)

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_msg
    fake_client.messages.count_tokens.return_value = fake_count

    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value = fake_client

    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        enricher = get_enricher("claude-api")
        result = enricher.enrich(
            "transcript text",
            "prompt with transcript text",
            task="summarize",
            confirm=False,
        )

    assert result.backend == "claude-api"
    assert result.text == "ok"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.cost_usd > 0  # priced from the ledger
    fake_client.messages.create.assert_called_once()
