"""PII redaction.

Two passes, both off by default:
1. Regex pass — best effort, only catches well-formatted PII (email, phone, SSN-like).
2. Local Ollama pass — better recall, requires Ollama running.

Caveats are documented in the README. The regex pass is NOT a substitute for
real DLP — it WILL miss names, addresses, and anything non-US-formatted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(
    r"(?:(?<!\d)\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
)
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


@dataclass
class RedactionReport:
    redacted: str
    counts: dict[str, int]


def redact_regex(text: str) -> RedactionReport:
    counts = {"email": 0, "phone": 0, "ssn": 0, "credit": 0}

    def _sub(pattern: re.Pattern[str], placeholder: str, key: str, t: str) -> str:
        def repl(_m: re.Match[str]) -> str:
            counts[key] += 1
            return placeholder
        return pattern.sub(repl, t)

    out = text
    out = _sub(EMAIL_RE, "[REDACTED_EMAIL]", "email", out)
    out = _sub(SSN_RE, "[REDACTED_SSN]", "ssn", out)
    out = _sub(CREDIT_RE, "[REDACTED_CC]", "credit", out)
    out = _sub(PHONE_RE, "[REDACTED_PHONE]", "phone", out)
    return RedactionReport(redacted=out, counts=counts)


_OLLAMA_REDACT_PROMPT = """\
You are a privacy filter. Replace personal information in the text below with
placeholders. Replace:
- Person names → [PERSON]
- Email addresses → [EMAIL]
- Phone numbers → [PHONE]
- Street addresses → [ADDRESS]
- Company names that identify the speaker's employer → [COMPANY]
- Any other clearly private identifier → [REDACTED]

Output ONLY the redacted text. No commentary.

---
{{transcript}}
"""


def redact_with_ollama(text: str) -> str:
    from .enrich.ollama import OllamaEnricher

    enricher = OllamaEnricher()
    prompt = _OLLAMA_REDACT_PROMPT.replace("{{transcript}}", text)
    res = enricher.enrich(text, prompt, task="redact")
    return res.text


def redact(text: str, *, use_ollama: bool = False) -> RedactionReport:
    """Run regex pass; optionally chain Ollama for better recall."""
    rep = redact_regex(text)
    if use_ollama:
        rep.redacted = redact_with_ollama(rep.redacted)
    return rep
