# ux570-transcribe

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)

Local-first transcription pipeline for the **Sony ICD-UX570** voice recorder, with optional Claude enrichment and an MCP server so Claude Desktop / Claude Code can search your archive directly.

## What this is

Plug in a UX570, run `ux570 watch`, and your recordings flow into a local archive: copied off the device, transcribed with Whisper, summarized with a local LLM, and indexed for full-text search. Claude features (summaries, action items, multi-step agent workflows, MCP) are **opt-in** and **per-call** — never silently triggered.

The pipeline is generic — the UX570 is just the default. Pass `--source <dir>` to `ingest` or `watch` to point it at any USB drive, network share, or local folder. If the Sony `REC_FILE/FOLDER01..05` layout is detected the device convention is used; otherwise the directory is walked recursively for any common audio format (`.mp3 .wav .m4a .mp4 .flac .ogg .aac .opus .webm`).

## Privacy model

There are two modes. The default never makes a network call.

| Mode | Audio | Transcript | Summarization |
|---|---|---|---|
| **Local (default)** | stays on disk | stays on disk | local Ollama |
| **Cloud (opt-in)** | stays on disk | sent to Claude API or Claude CLI | Anthropic |

- **Audio never leaves your machine**, in either mode. Even agents see only the transcript text.
- **API keys are stored in the OS keychain** (Keychain on macOS, Secret Service on Linux), never in `.env`, never logged.
- **Audit log** at `~/.ux570/audit.log` records every cloud call: timestamp, backend, model, transcript SHA-256, first 80 characters, token counts, cost. The transcript content itself is not written.
- **Fully offline mode is real.** With `DEFAULT_ENRICH_BACKEND=ollama` and `--backend ollama`, you can verify with `nettop`/`tcpdump` that no traffic leaves the machine. The Claude SDK isn't even imported.

## Prerequisites

- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/) (or pip)
- **ffmpeg** — for audio decoding (`brew install ffmpeg` / `apt install ffmpeg`)

Optional, depending on which features you want:

- **Ollama** — local LLM for summarization. `brew install ollama` then `ollama serve` and `ollama pull qwen2.5:7b`.
- **`claude` CLI** — Claude Code CLI, for the `claude-cli` enrichment backend and `--interactive` agent mode.
- **Anthropic API key** — for the `claude-api` backend and most agent workflows.

## Quick start (local mode)

```bash
git clone https://github.com/BaruchEric/ux570-transcribe.git
cd ux570-transcribe
uv pip install -e .

# Copy the env template and tweak as needed.
cp .env.example .env

# Plug in the UX570, then:
ux570 ingest         # copy new recordings to the archive
ux570 transcribe 'archive/**/audio.mp3'

# Or, in one shot:
ux570 watch          # daemon: ingest+transcribe whenever the device is plugged in
ux570 watch --enrich # also runs the default Ollama summarizer

# Any other audio source — a folder, USB drive, network share, etc.:
ux570 ingest --source ~/Dropbox/voice-memos
ux570 watch  --source ~/Dropbox/voice-memos --once
```

Search later:

```bash
ux570 search "sarah AND project"
```

The archive lives at `~/Documents/ux570-archive/<YYYY>/<YYYY-MM-DD>/<HH-MM>_<sha8>/` and contains:

- `audio.mp3` — the original file (read-only)
- `transcript.txt` — plain text
- `transcript.srt` — subtitles
- `transcript.md` — metadata + transcript + appended enrichments

## Adding Claude

Claude features are an extra, paid layer. Install the extras and store your key:

```bash
uv pip install -e '.[cloud]'
ux570 config set-key anthropic     # prompts; key goes to OS keychain
```

Then pick a backend per call:

```bash
ux570 enrich archive/2026/2026-04-27/14-30_abcd1234/ \
  --backend claude-api \
  --task meeting_notes
```

### Cost expectations

Defaults use **`claude-sonnet-4-6`** (cheaper/faster). Agent workflows default to **`claude-opus-4-7`** (higher quality, ~5× the cost).

Real example, a 30-minute meeting:

| Step | Tokens (in/out) | Sonnet | Opus |
|---|---|---|---|
| Summarize | 6,000 / 400 | $0.024 | $0.120 |
| Meeting notes | 6,000 / 800 | $0.030 | $0.150 |
| Action items | 6,000 / 300 | $0.022 | $0.113 |
| Follow-up email | 6,000 / 200 | $0.021 | $0.105 |
| `agent meeting-debrief` total | ~ | **$0.10** | **$0.49** |

The daily cap (`MAX_DAILY_CLAUDE_USD`, default `$5.00`) is enforced **before** any call is sent. Hitting the cap raises an error — there's no silent failover.

`ux570 stats` shows your spend:

```
ux570 stats --days 30
```

### Redact before sending

Regex catches email/phone/SSN/credit-card patterns. A local Ollama pass also strips names and addresses (better recall, still imperfect):

```bash
ux570 redact archive/.../transcript.txt --ollama --out cleaned.txt
ux570 enrich cleaned.txt --backend claude-api --task summarize
```

The README is honest: regex alone is **not** real DLP. Run with `--ollama` for anything sensitive.

## Whisper model size guide

`WHISPER_MODEL` defaults to `small.en`. Pick based on hardware:

| Model | Disk | RAM | Speed (M-series) | Speed (CPU) | Quality |
|---|---|---|---|---|---|
| `tiny.en` | 75 MB | ~1 GB | ~30× real-time | ~10× | rough |
| `base.en` | 142 MB | ~1 GB | ~16× | ~5× | usable |
| `small.en` | 466 MB | ~2 GB | ~6× | ~2× | **good default** |
| `medium.en` | 1.5 GB | ~5 GB | ~2× | <1× | great on M-series |
| `large-v3` | 2.9 GB | ~10 GB | ~1× | painful | best |

`compute_type=int8` is the right default; switch to `float16` only on Nvidia GPUs.

## Writing custom prompts and agent workflows

### Prompts

Drop a file in `prompts/<task>.md`. Use `{{transcript}}` as the placeholder for the transcript body. The CLI auto-discovers it:

```bash
ux570 enrich /path/to/transcript.txt --task my-custom-task
```

### Agent workflows

A workflow is a YAML file with a `steps` list. Each step has a `name`, an `output` filename, and either a `template` (referencing `prompts/<template>.md`) or an inline `prompt`:

```yaml
steps:
  - name: tldr
    template: summarize
    output: tldr.md
  - name: facts-only
    output: facts.md
    prompt: |
      Extract only verifiable factual claims from the transcript below.
      Output a numbered list. Skip opinions and intentions.

      ---

      {{transcript}}
```

Run it:

```bash
ux570 agent custom archive/.../transcript.txt --workflow my_workflow.yaml
```

## MCP server

Expose your transcript archive to Claude Desktop or Claude Code:

```bash
uv pip install -e '.[mcp]'
```

Add this to your Claude Desktop / Claude Code MCP config:

```json
{
  "mcpServers": {
    "ux570": { "command": "ux570-mcp" }
  }
}
```

Tools the server provides:

- `search_transcripts(query, limit)` — FTS5 search
- `get_transcript(recording_id)` — full text
- `list_recent(limit)` — recent recordings
- `list_enrichments(recording_id)` — past summaries/agent outputs

Now you can ask Claude: *"What did I talk about with Sarah last week?"* and it queries this archive directly.

## Troubleshooting

**Device not detected.**
On macOS, look for a `/Volumes/IC RECORDER` folder. If it's not there, the recorder may need its date set or its USB cable replaced. `diskutil list` will show whether the OS sees it.

**Ollama call fails.**
Check `ollama serve` is running and `ollama list` shows the model in `OLLAMA_MODEL`. The CLI does not silently fall back to anything else — that's intentional.

**`whisper-medium` is too slow on my Intel Mac.**
Switch to `small.en` in `.env` or `tiny.en` for raw speed. Quality drops noticeably below `small`.

**"No Anthropic API key in OS keychain."**
Run `ux570 config set-key anthropic`. The key goes to Keychain (macOS) or Secret Service (Linux). To rotate, run the command again — it overwrites.

**Cost-cap error mid-day.**
Raise `MAX_DAILY_CLAUDE_USD` in `.env`, or wait until tomorrow. The cap is per local calendar day.

## FAQ

**Q: Does this send my recordings to Anthropic?**
A: No. Audio never leaves your machine in any mode. In cloud mode, only the transcript text is sent. To verify: `cat ~/.ux570/audit.log` lists every cloud call (transcript hash + first 80 chars only); `lsof -i` while running confirms no `claude.ai`/`anthropic.com` connections in local mode.

**Q: What does "local mode" actually mean?**
A: With `--backend ollama` (or `DEFAULT_ENRICH_BACKEND=ollama` and no override), the only outbound traffic is to `127.0.0.1:11434` (your local Ollama). The `anthropic` SDK is lazily imported and never loaded in local mode.

**Q: Where do I find the data?**
A: Three locations: archive at `~/Documents/ux570-archive/`, state at `~/.ux570/` (DB, audit log, enrich log), and OS keychain entries under `ux570-transcribe`.

**Q: How do I uninstall cleanly?**
A: `uv pip uninstall ux570-transcribe`, `rm -rf ~/.ux570 ~/Documents/ux570-archive`, then delete the `ux570-transcribe` keychain entries (Keychain Access → search "ux570").

## Development

```bash
uv pip install -e '.[dev,all]'
ruff check .
pytest
```

Tests use a tmp-dir-isolated SQLite DB and never touch your real archive or keychain.

## License

[MIT](LICENSE) © Eric Baruch
