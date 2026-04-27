"""Regex redaction sanity."""

from __future__ import annotations

from ux570_transcribe.redact import redact_regex


def test_redact_email_phone_ssn():
    text = "Email me at jane.doe@example.com or call 415-555-1234. SSN 123-45-6789."
    rep = redact_regex(text)
    assert "jane.doe@example.com" not in rep.redacted
    assert "415-555-1234" not in rep.redacted
    assert "123-45-6789" not in rep.redacted
    assert rep.counts == {"email": 1, "phone": 1, "ssn": 1, "credit": 0}


def test_redact_does_not_touch_names():
    text = "John talked to Mary about the project."
    rep = redact_regex(text)
    # Regex pass intentionally does NOT redact names — that's documented.
    assert "John" in rep.redacted
    assert "Mary" in rep.redacted
