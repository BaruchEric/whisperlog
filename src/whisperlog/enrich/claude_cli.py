"""Wraps the local `claude` CLI as an enrichment backend.

Two modes:
- Default: `claude --print "<prompt>"` with transcript inlined or via temp file.
- --interactive: drops user into a Claude Code session pre-loaded with transcript.

No token accounting (the CLI doesn't expose it). Logged as backend=claude-cli
with zero cost since billing happens against the user's Claude subscription.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import get_settings
from .base import Backend, Enricher, EnrichResult

logger = logging.getLogger(__name__)

INSTALL_HINT = (
    "Claude Code CLI not found on PATH. Install: https://claude.ai/code\n"
    "Or set CLAUDE_CLI_PATH=/absolute/path/to/claude in your .env."
)

# 8KB threshold: above this we hand Claude the file via --add-dir instead of inlining.
INLINE_LIMIT_BYTES = 8 * 1024


class ClaudeCLINotFound(RuntimeError):
    pass


class ClaudeCLIEnricher(Enricher):
    backend: Backend = "claude-cli"

    def _resolve_binary(self) -> str:
        configured = get_settings().claude_cli_path
        path = shutil.which(configured)
        if path is None:
            # Only honor the configured value as a literal path if it's absolute,
            # so a CWD file named "claude" can't hijack the default.
            cp = Path(configured)
            if cp.is_absolute() and cp.is_file():
                path = configured
        if not path:
            raise ClaudeCLINotFound(INSTALL_HINT)
        return path

    def enrich(
        self,
        transcript: str,
        prompt: str,
        *,
        task: str,
        interactive: bool = False,
        transcript_path: Path | None = None,
        timeout_secs: int = 600,
        **_,
    ) -> EnrichResult:
        binary = self._resolve_binary()

        if interactive:
            return self._run_interactive(binary, transcript, prompt, task, transcript_path)

        # Decide inline vs. file-based prompt.
        with tempfile.TemporaryDirectory(prefix="whisperlog-cli-") as td:
            tdir = Path(td)
            cwd = tdir
            if len(prompt.encode("utf-8")) > INLINE_LIMIT_BYTES:
                prompt_file = tdir / "prompt.md"
                transcript_file = tdir / "transcript.txt"
                # Strip the inlined transcript out of the prompt; reference it instead.
                transcript_file.write_text(transcript, encoding="utf-8")
                prompt_only = prompt.replace(transcript, "(see transcript.txt in this dir)")
                prompt_file.write_text(prompt_only, encoding="utf-8")
                argv = [
                    binary, "--print",
                    "Read prompt.md and transcript.txt in this directory, then respond to the prompt.",
                    "--add-dir", str(tdir),
                ]
            else:
                argv = [binary, "--print", prompt]

            logger.info("Running Claude CLI: %s ... (task=%s)", argv[0], task)
            try:
                proc = subprocess.run(
                    argv,
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=timeout_secs,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"Claude CLI timed out after {timeout_secs}s") from e

            if proc.returncode != 0:
                raise RuntimeError(
                    f"Claude CLI exited {proc.returncode}.\n"
                    f"stderr: {proc.stderr.strip()[:1000]}"
                )

            text = proc.stdout.strip()

        return self._finalize(
            transcript=transcript,
            transcript_path=transcript_path,
            task=task,
            model=None,
            text=text,
            in_tok=0,
            out_tok=0,
            cost=0.0,
        )

    def _run_interactive(
        self,
        binary: str,
        transcript: str,
        prompt: str,
        task: str,
        transcript_path: Path | None,
    ) -> EnrichResult:
        # Stage transcript + prompt to a temp dir so the user has both pre-loaded.
        td = Path(tempfile.mkdtemp(prefix="whisperlog-cli-int-"))
        (td / "transcript.txt").write_text(transcript, encoding="utf-8")
        (td / "prompt.md").write_text(prompt, encoding="utf-8")
        readme = (
            f"# whisperlog interactive session\n\n"
            f"Task: {task}\n"
            f"Transcript: transcript.txt ({len(transcript)} chars)\n"
            f"Prompt: prompt.md\n\n"
            f"Ask Claude Code anything about the transcript.\n"
        )
        (td / "README.md").write_text(readme, encoding="utf-8")

        argv = [binary, "--add-dir", str(td)]
        logger.info("Launching interactive Claude Code session in %s", td)
        # Inherit stdio so the user can drive Claude Code directly.
        subprocess.run(argv, cwd=str(td))
        return self._finalize(
            transcript=transcript,
            transcript_path=transcript_path,
            task=task + ":interactive",
            model=None,
            text=f"(interactive session ran in {td})",
            in_tok=0,
            out_tok=0,
            cost=0.0,
            extras={"workdir": str(td)},
        )


__all__ = ["ClaudeCLIEnricher", "ClaudeCLINotFound"]
