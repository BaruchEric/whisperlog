"""Typer CLI for ux570-transcribe."""

from __future__ import annotations

import glob
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import get_settings
from .utils import setup_logging

app = typer.Typer(
    name="ux570",
    help="Local-first transcription pipeline for Sony ICD-UX570.",
    no_args_is_help=True,
)
config_app = typer.Typer(help="Manage config and secrets.")
agent_app = typer.Typer(help="Multi-step Claude agent workflows.")
app.add_typer(config_app, name="config")
app.add_typer(agent_app, name="agent")

console = Console()
logger = logging.getLogger("ux570.cli")


@app.callback()
def _root(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    setup_logging(verbose=verbose)


@app.command()
def version() -> None:
    """Print version."""
    typer.echo(__version__)


# ----------------------------- ingest -----------------------------

@app.command()
def ingest(
    eject_after: bool = typer.Option(True, "--eject/--no-eject"),
) -> None:
    """Detect UX570, copy new recordings to the archive, eject."""
    from .ingest import detect_mount_point, ingest_from_mount
    from .ingest import eject as do_eject

    mount = detect_mount_point()
    if not mount:
        console.print("[yellow]No UX570 detected.[/yellow] "
                      "Plug it in and confirm it shows up under /Volumes (macOS) or /media (Linux).")
        raise typer.Exit(code=1)
    console.print(f"Found device at [cyan]{mount}[/cyan]")
    results = ingest_from_mount(mount)
    new = sum(1 for _, is_new in results if is_new)
    total = len(results)
    console.print(f"Ingested {new} new file(s) ({total} on device)")
    if eject_after:
        if do_eject(mount):
            console.print(f"Ejected {mount}")
        else:
            console.print(f"[yellow]Could not eject {mount}[/yellow]")


# ----------------------------- transcribe -----------------------------

@app.command()
def transcribe(
    file_or_glob: str = typer.Argument(..., help="Path or glob (e.g. archive/2026/2026-04-27/**/audio.mp3)"),
) -> None:
    """Transcribe local audio files (already-ingested or ad-hoc)."""
    from .archive import find_by_archive_path
    from .ingest import ingest_file
    from .transcribe import transcribe_recording

    paths = [Path(p) for p in sorted(glob.glob(file_or_glob, recursive=True))]
    if not paths:
        # Maybe it's a literal path
        p = Path(file_or_glob)
        if p.is_file():
            paths = [p]
    if not paths:
        console.print(f"[red]No files matched:[/red] {file_or_glob}")
        raise typer.Exit(code=1)

    for p in paths:
        rec = find_by_archive_path(p)
        if rec is None:
            rec, _ = ingest_file(p)
        _txt, _srt, md, result = transcribe_recording(rec)
        console.print(f"  [green]✓[/green] {p.name}  →  {md}  "
                      f"({result.duration:.1f}s, lang={result.language})")


# ----------------------------- watch -----------------------------

@app.command()
def watch(
    poll: float = typer.Option(3.0, help="Poll interval in seconds"),
    enrich: bool = typer.Option(False, help="Run default enricher after each transcription"),
    eject_after: bool = typer.Option(True, "--eject/--no-eject"),
    once: bool = typer.Option(False, "--once", help="Run one cycle and exit"),
) -> None:
    """Daemon: ingest+transcribe new recordings whenever the UX570 is plugged in."""
    from .watch import watch_loop

    watch_loop(poll_secs=poll, enrich=enrich, eject_after=eject_after, once=once)


# ----------------------------- search -----------------------------

@app.command()
def search(
    query: str = typer.Argument(...),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Full-text search across all transcripts."""
    from .archive import search as do_search

    hits = do_search(query, limit=limit)
    if not hits:
        console.print("[yellow]No matches.[/yellow]")
        raise typer.Exit(code=1)
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", justify="right")
    table.add_column("Folder")
    table.add_column("Snippet")
    for h in hits:
        table.add_row(str(h.recording_id), str(h.archive_path.parent), h.snippet)
    console.print(table)


# ----------------------------- enrich -----------------------------

@app.command()
def enrich(
    transcript: Path = typer.Argument(..., help="Path to a transcript file or archive folder"),
    backend: str | None = typer.Option(None, help="ollama | claude-api | claude-cli"),
    task: str | None = typer.Option(None, help="Prompt template name (without .md)"),
    model: str | None = typer.Option(None, help="Override model (Claude API only)"),
    yes: bool = typer.Option(False, "--yes", help="Skip cost confirmation"),
) -> None:
    """Run an enrichment pass on a transcript and append to its .md."""
    from .archive import append_enrichment_to_md, record_enrichment_for_folder
    from .enrich import get_enricher, load_prompt_template, render_prompt

    s = get_settings()
    backend_choice = backend or s.default_enrich_backend
    task_choice = task or s.default_enrich_task

    text, md_path = _resolve_text_and_md(transcript)
    template = load_prompt_template(task_choice)
    prompt = render_prompt(template, text)

    enricher = get_enricher(backend_choice)  # type: ignore[arg-type]
    kwargs: dict = {"task": task_choice, "transcript_path": transcript}
    if backend_choice == "claude-api":
        kwargs["confirm"] = not yes
        if model:
            kwargs["model"] = model

    result = enricher.enrich(text, prompt, **kwargs)

    append_enrichment_to_md(md_path, result.text, result.backend, task_choice)
    console.print(
        f"[green]✓[/green] {result.backend} {task_choice} → {md_path}  "
        f"(in={result.input_tokens} out={result.output_tokens} cost=${result.cost_usd:.4f})"
    )
    record_enrichment_for_folder(md_path.parent, text, result)


def _resolve_text_and_md(p: Path) -> tuple[str, Path]:
    p = p.expanduser().resolve()
    if p.is_dir():
        md = p / "transcript.md"
        if md.is_file():
            return md.read_text(encoding="utf-8"), md
        txt = p / "transcript.txt"
        if txt.is_file():
            return txt.read_text(encoding="utf-8"), p / "transcript.md"
        raise FileNotFoundError(f"No transcript in {p}")
    if p.suffix == ".md":
        return p.read_text(encoding="utf-8"), p
    if p.is_file():
        # plain text — write enrichment beside it as <name>.md
        return p.read_text(encoding="utf-8"), p.with_suffix(".md")
    raise FileNotFoundError(p)


# ----------------------------- redact -----------------------------

@app.command()
def redact(
    transcript: Path = typer.Argument(...),
    use_ollama: bool = typer.Option(False, "--ollama", help="Also run a local Ollama redaction pass"),
    output: Path | None = typer.Option(None, "--out", help="Write redacted output to this path"),
) -> None:
    """Strip PII from a transcript with regex (and optionally a local Ollama pass)."""
    from .redact import redact as do_redact

    text = transcript.read_text(encoding="utf-8") if transcript.is_file() else _resolve_text_and_md(transcript)[0]
    rep = do_redact(text, use_ollama=use_ollama)
    out_path = output or transcript.with_suffix(transcript.suffix + ".redacted.txt")
    out_path.write_text(rep.redacted, encoding="utf-8")
    console.print(f"[green]✓[/green] Redacted → {out_path}")
    console.print(f"  Counts: {rep.counts}")
    if not use_ollama:
        console.print("[yellow]Note:[/yellow] regex catches email/phone/SSN/credit-card only. "
                      "Use --ollama to also strip names/addresses (requires local Ollama).")


# ----------------------------- stats -----------------------------

@app.command()
def stats(days: int = typer.Option(7, "--days", "-d")) -> None:
    """Show Claude API spend over the last N days."""
    from .ledger import daily_total_usd, summary_last_n_days

    s = get_settings()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Day")
    table.add_column("Cost USD", justify="right")
    table.add_column("Input tok", justify="right")
    table.add_column("Output tok", justify="right")
    rows = summary_last_n_days(days)
    if not rows:
        console.print("[yellow]No spend recorded yet.[/yellow]")
        return
    for r in rows:
        table.add_row(r.day, f"${r.total_usd:.4f}", f"{r.input_tokens:,}", f"{r.output_tokens:,}")
    console.print(table)
    console.print(f"Daily cap: [bold]${s.max_daily_claude_usd:.2f}[/bold]   "
                  f"Spent today: [bold]${daily_total_usd():.4f}[/bold]")


# ----------------------------- config -----------------------------

@config_app.command("set-key")
def config_set_key(provider: str = typer.Argument(...)) -> None:
    """Store an API key in the OS keychain. Currently supported: anthropic."""
    if provider != "anthropic":
        console.print(f"[red]Unknown provider:[/red] {provider}. Supported: anthropic")
        raise typer.Exit(code=2)
    from .secrets import prompt_and_store_anthropic_key
    prompt_and_store_anthropic_key()
    console.print("[green]✓[/green] Stored in OS keychain.")


@config_app.command("show")
def config_show() -> None:
    """Print current effective config (no secrets)."""
    s = get_settings()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Key")
    table.add_column("Value")
    for k in (
        "ux570_archive_dir", "ux570_state_dir", "whisper_model", "whisper_device",
        "whisper_compute_type", "enable_vad", "default_enrich_backend",
        "default_enrich_task", "ollama_host", "ollama_model",
        "claude_model", "claude_agent_model", "max_daily_claude_usd",
    ):
        table.add_row(k, str(getattr(s, k)))
    console.print(table)
    from .secrets import get_anthropic_key
    has_key = bool(get_anthropic_key())
    console.print(f"Anthropic key in keychain: [{'green' if has_key else 'yellow'}]{has_key}[/]")


# ----------------------------- agent -----------------------------

@agent_app.command("meeting-debrief")
def agent_meeting(
    transcript: Path = typer.Argument(...),
    backend: str = typer.Option("claude-api", help="claude-api | claude-cli"),
    model: str | None = typer.Option(None),
) -> None:
    """Notes + action items + follow-up email + .ics, all from one transcript."""
    from .agent import meeting_debrief
    outs = meeting_debrief(transcript, backend=backend, model=model)  # type: ignore[arg-type]
    for o in outs:
        console.print(f"[green]✓[/green] {o.name}: {o.path}  (cost ${o.cost_usd:.4f})")


@agent_app.command("code-review")
def agent_code_review(
    transcript: Path = typer.Argument(...),
    backend: str = typer.Option("claude-api"),
    model: str | None = typer.Option(None),
    repo: Path | None = typer.Option(None, help="If set, propose code changes via Claude CLI"),
) -> None:
    """Extract decisions, open questions, and (optionally) propose code changes."""
    from .agent import code_review
    outs = code_review(transcript, backend=backend, model=model, repo=repo)  # type: ignore[arg-type]
    for o in outs:
        console.print(f"[green]✓[/green] {o.name}: {o.path}")


@agent_app.command("custom")
def agent_custom(
    transcript: Path = typer.Argument(...),
    workflow: Path = typer.Option(..., "--workflow", help="YAML workflow file"),
    backend: str = typer.Option("claude-api"),
    model: str | None = typer.Option(None),
) -> None:
    """Run a YAML-defined sequence of prompts."""
    from .agent import custom_workflow
    outs = custom_workflow(transcript, workflow, backend=backend, model=model)  # type: ignore[arg-type]
    for o in outs:
        console.print(f"[green]✓[/green] {o.name}: {o.path}")


# ----------------------------- entrypoint -----------------------------

if __name__ == "__main__":
    app()
