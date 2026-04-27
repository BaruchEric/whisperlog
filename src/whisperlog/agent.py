"""Multi-step Claude agent workflows.

Workflows take a transcript path and produce structured outputs in the same
date folder. Each workflow uses the Claude API by default with the configured
agent model (claude-opus-4-7), unless --backend overrides it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .archive import record_enrichment_for_folder
from .config import get_settings
from .enrich import Enricher, EnrichResult, load_prompt_template, render_prompt

logger = logging.getLogger("whisperlog.agent")

AgentBackend = Literal["claude-api", "claude-cli"]


@dataclass
class AgentOutput:
    name: str
    path: Path
    summary: str
    cost_usd: float = 0.0


def _resolve_transcript(transcript: Path) -> tuple[str, Path]:
    """Accept either an audio archive folder, a transcript file, or a free-standing .txt path.

    Returns (transcript_text, folder_for_outputs).
    """
    p = transcript.expanduser().resolve()
    if p.is_dir():
        for name in ("transcript.txt", "transcript.md"):
            f = p / name
            if f.is_file():
                return f.read_text(encoding="utf-8"), p
        raise FileNotFoundError(f"No transcript found in {p}")
    if p.is_file():
        return p.read_text(encoding="utf-8"), p.parent
    raise FileNotFoundError(f"Not a file or dir: {p}")


def _enricher_for(backend: AgentBackend, model_override: str | None) -> Enricher:
    if backend == "claude-api":
        from .enrich.claude_api import ClaudeAPIEnricher
        return ClaudeAPIEnricher(model=model_override or get_settings().claude_agent_model)
    if backend == "claude-cli":
        from .enrich.claude_cli import ClaudeCLIEnricher
        return ClaudeCLIEnricher()
    raise ValueError(f"Agents support claude-api or claude-cli only, got {backend}")


def _run_step(
    enricher: Enricher,
    template_name: str,
    transcript: str,
    *,
    task_label: str,
) -> EnrichResult:
    template = load_prompt_template(template_name)
    prompt = render_prompt(template, transcript)
    return enricher.enrich(transcript, prompt, task=task_label)


# ---------- meeting-debrief ----------

_DEBRIEF_STEPS = [
    ("meeting_notes", "meeting-notes", "meeting-notes", "meeting_notes.md", None),
    ("action_items", "action-items", "action-items", "action_items.md", None),
    ("followup_email", "followup-email", "followup-email", "followup_email.eml", lambda t: _wrap_eml(t)),
    ("calendar_ics", "calendar-ics", "calendar", "mentioned_events.ics", lambda t: _wrap_ics(t)),
]


def meeting_debrief(
    transcript: Path,
    *,
    backend: AgentBackend = "claude-api",
    model: str | None = None,
) -> list[AgentOutput]:
    """Multi-step debrief: notes, action items, follow-up email, calendar .ics."""
    text, folder = _resolve_transcript(transcript)
    enricher = _enricher_for(backend, model)
    outputs: list[AgentOutput] = []
    total_cost = 0.0

    for template, task_label, output_name, filename, wrap in _DEBRIEF_STEPS:
        res = _run_step(enricher, template, text, task_label=task_label)
        body = wrap(res.text) if wrap else res.text + "\n"
        path = folder / filename
        path.write_text(body, encoding="utf-8")
        outputs.append(AgentOutput(output_name, path, res.text[:200], res.cost_usd))
        total_cost += res.cost_usd
        record_enrichment_for_folder(folder, text, res)

    logger.info("meeting-debrief complete. Total cost: $%.4f", total_cost)
    return outputs


def _wrap_eml(body: str) -> str:
    """Wrap the LLM-drafted body as a minimal RFC822 message ready to import or send."""
    return (
        "From: me@example.com\n"
        "To: \n"
        "Subject: Meeting follow-up\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "MIME-Version: 1.0\n"
        f"Date: {datetime.now().astimezone().strftime('%a, %d %b %Y %H:%M:%S %z')}\n"
        "\n"
        f"{body.strip()}\n"
    )


def _wrap_ics(body: str) -> str:
    """If the model already produced a VCALENDAR, pass through. Otherwise wrap as a NOTE event."""
    b = body.strip()
    if b.startswith("BEGIN:VCALENDAR"):
        return b + ("\n" if not b.endswith("\n") else "")
    # Fallback: emit a single all-day VEVENT carrying the model's text as DESCRIPTION.
    today = datetime.now().strftime("%Y%m%dT%H%M%S")
    description = b.replace("\n", "\\n")[:500]
    return (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//whisperlog//agent//EN\n"
        "BEGIN:VEVENT\n"
        f"UID:{today}@whisperlog\n"
        f"DTSTAMP:{today}\n"
        "SUMMARY:Mentioned events (review)\n"
        f"DESCRIPTION:{description}\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )


# ---------- code-review ----------

def code_review(
    transcript: Path,
    *,
    backend: AgentBackend = "claude-api",
    model: str | None = None,
    repo: Path | None = None,
) -> list[AgentOutput]:
    text, folder = _resolve_transcript(transcript)
    outputs: list[AgentOutput] = []

    if repo is not None and backend != "claude-cli":
        logger.info("Repo provided; switching to claude-cli for in-repo proposals.")
        backend = "claude-cli"

    enricher = _enricher_for(backend, model)

    res = _run_step(enricher, "coding_session", text, task_label="code-review")
    summary_path = folder / "code_review.md"
    summary_path.write_text(res.text + "\n", encoding="utf-8")
    outputs.append(AgentOutput("code-review", summary_path, res.text[:200], res.cost_usd))
    record_enrichment_for_folder(folder, text, res)

    if repo is not None:
        from .enrich.claude_cli import ClaudeCLIEnricher
        cli = ClaudeCLIEnricher()
        prompt = (
            f"You have access to the repo at: {repo}\n\n"
            "Below is a transcript of a design/pair-programming discussion. "
            "Propose concrete code changes referencing files in the repo. "
            "DO NOT modify files yet — just propose.\n\n---\n\n" + text
        )
        cli.enrich(text, prompt, task="code-review:propose", transcript_path=transcript)

    return outputs


# ---------- custom YAML-defined workflow ----------

def custom_workflow(
    transcript: Path,
    workflow_path: Path,
    *,
    backend: AgentBackend = "claude-api",
    model: str | None = None,
) -> list[AgentOutput]:
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError(
            "PyYAML required for custom workflows. Install with `[agent]` extras."
        ) from e

    text, folder = _resolve_transcript(transcript)
    enricher = _enricher_for(backend, model)

    spec = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or "steps" not in spec:
        raise ValueError("Workflow YAML must be a mapping with a 'steps' list.")

    outputs: list[AgentOutput] = []
    for step in spec["steps"]:
        name = step["name"]
        template = step.get("template")
        prompt_inline = step.get("prompt")
        if template:
            tpl = load_prompt_template(template)
            prompt = render_prompt(tpl, text)
        elif prompt_inline:
            prompt = render_prompt(str(prompt_inline), text)
        else:
            raise ValueError(f"Step '{name}' must specify 'template' or 'prompt'.")

        out_filename = step.get("output", f"{name}.md")
        res = enricher.enrich(text, prompt, task=name)
        out_path = folder / out_filename
        out_path.write_text(res.text + "\n", encoding="utf-8")
        outputs.append(AgentOutput(name, out_path, res.text[:200], res.cost_usd))
        record_enrichment_for_folder(folder, text, res)

    return outputs
