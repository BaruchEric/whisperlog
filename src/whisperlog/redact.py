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
# Phone: optional country code, then 3-3-4 with at least one separator-bearing
# canonical form. Anchor both ends so digit-heavy IDs don't match.
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"
)
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Credit card: require separator-bearing groups (raw 13-19-digit blobs are not
# matched — Luhn would be more accurate but adds dep noise).
CREDIT_RE = re.compile(r"(?<!\d)(?:\d{4}[ -]){3}\d{3,4}(?!\d)")


@dataclass
class RedactionReport:
    redacted: str
    counts: dict[str, int]
    ollama_used: bool = False


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
    from .enrich.base import render_prompt
    from .enrich.ollama import OllamaEnricher

    prompt = render_prompt(_OLLAMA_REDACT_PROMPT, text)
    res = OllamaEnricher().enrich(text, prompt, task="redact")
    return res.text


def redact(text: str, *, use_ollama: bool = False) -> RedactionReport:
    """Run regex pass; optionally chain Ollama for better recall.

    `counts` reflects only the regex pass — Ollama replacements are not counted,
    which is signaled by `ollama_used`.
    """
    rep = redact_regex(text)
    if use_ollama:
        rep.redacted = redact_with_ollama(rep.redacted)
        rep.ollama_used = True
    return rep
