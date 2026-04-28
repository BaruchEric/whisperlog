# Code Simplify Report: whisperlog (full repo)

**Scanned**: 27 Python files, ~2877 LOC
**Baseline**: 3 ruff E702 errors in tests/test_ingest_dedup.py:46 (multi-statement semicolons — pre-existing)

## High Severity

- **src/whisperlog/enrich/claude_cli.py:48** [correctness] — `_resolve_binary` falls back to `Path(configured).is_file()` when `shutil.which` misses; with the default `claude_cli_path = "claude"` this resolves a `claude` file in the **current working directory**. Running `whisperlog` from a directory containing a hostile file named `claude` would execute it. **Fix**: only honor the fallback when the configured value is an absolute path: `path = shutil.which(configured) or (configured if Path(configured).is_absolute() and Path(configured).is_file() else None)`.

- **src/whisperlog/ledger.py:64-87 / src/whisperlog/enrich/claude_api.py:97-98** [correctness] — Spend-cap enforcement is non-atomic: `assert_within_cap` reads `daily_total_usd`, the request runs, then `record_spend` inserts in a separate transaction. Two concurrent processes can both pass the check and both spend, exceeding the cap. **Fix**: make `record_spend` perform the cap check inside `BEGIN IMMEDIATE` — re-query the day's total inside the same transaction and raise `SpendCapExceeded` (rolling back) if the new row would exceed. Keep `assert_within_cap` as a pre-flight UX nicety only.

- **src/whisperlog/ledger.py:46-47 vs 91** [correctness] — Day boundary inconsistency: `_today_iso` uses `date.today()` (local), `summary_last_n_days` uses `datetime.now(UTC).date()` (UTC). Spend rows are written with local-day labels but the summary cutoff is UTC, so totals can omit/include a day's worth of spend near midnight. User instruction is "timestamps are local midnight, not UTC midnight" — pick local everywhere. **Fix**: `cutoff = (datetime.now().astimezone().date() - timedelta(days=n - 1)).isoformat()`.

- **src/whisperlog/agent.py:200-220** [correctness] — `custom_workflow` reads `step["name"]` and uses it as a filename via `f"{name}.md"`/`step.get("output", ...)` joined to `folder`. A YAML step with `name: "../../escape"` writes outside the archive folder. Self-inflicted (user-authored YAML) but cheap to harden. **Fix**: validate `name`: reject empty, reject any of `os.sep`, `/`, `\\`, `..`. Also reject `out_filename` containing those.

- **src/whisperlog/agent.py:176** [correctness] — In `code_review`, the `claude-cli` propose pass calls `cli.enrich(...)` and **drops the return value** — no `outputs.append`, no `record_enrichment_for_folder`, no on-disk artifact. The user gets the initial summary but the in-repo proposal vanishes. **Fix**: capture `res = cli.enrich(...)`, write `code_review_propose.md`, append to `outputs`, and call `record_enrichment_for_folder`.

- **src/whisperlog/agent.py:127** [correctness] — `_wrap_ics` uses naive `datetime.now()` for `DTSTAMP`. RFC 5545 requires `DTSTAMP` to be UTC (`Z`-suffixed) or explicitly TZID-anchored; floating local time is invalid for DTSTAMP and rejected by stricter calendar clients. **Fix**: `today = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")`.

## Medium Severity

### Quality / reuse

- **src/whisperlog/watch.py:71-111** — `watch_loop` (UX570 branch) and `_watch_source` share the same shape: detect-change → `ingest_from_path` → split new/all → log → `_process_pending` → optional eject → sleep. **Fix**: extract `_run_cycle(source, *, enrich, eject_after, mount_mode, prev_state) -> state` so both loops are `while True: state = _run_cycle(...); if once: return; sleep`.

- **src/whisperlog/agent.py:50-57** vs **src/whisperlog/enrich/base.py:128** — Two parallel backend→enricher dispatch tables. `_enricher_for` exists only to inject a model override and to reject ollama. **Fix**: extend `get_enricher(backend, *, model=None)` to forward a model override into `ClaudeAPIEnricher(model=...)` and inline the ollama rejection at the agent call sites; delete `_enricher_for`.

- **src/whisperlog/ingest.py:121-123** — `ingest_from_mount` is a "backwards-compat" alias with **no callers** (cli.py and watch.py both use `ingest_from_path`). **Fix**: delete.

- **src/whisperlog/transcribe.py:118-120** — `transcribe_path` is a one-line wrapper around `transcribe_audio` with **no callers**. **Fix**: delete.

- **Cross-file (cli.py / watch.py × 2)** — `results = ingest_from_path(...); new_recs = [r for r,n in results if n]; all_recs = [r for r,_ in results]; logger.info("Ingested %d new (of %d total)", ...)` repeats verbatim 3 times. **Fix**: helper `partition_ingest(results) -> tuple[list[Recording], list[Recording]]` in ingest.py.

- **Cross-file (claude_api.py:127-131, claude_cli.py:108-112, claude_cli.py:145-149, ollama.py)** — All three backends end with the same audit + log + return shape. **Fix**: add `Enricher._finalize(*, transcript, transcript_path, task, model, text, in_tok, out_tok, cost, extras=None)` on the base class that runs `audit_cloud_call` (gated on `backend != "ollama"`) + `log_enrich_call` and returns the `EnrichResult`. Each backend body shrinks ~10 lines.

- **Cross-file (claude_api.py:31-38, mcp_server.py imports, agent.py:191-195)** — Three optional-dependency `try: import X except ImportError: raise RuntimeError(...)` blocks with subtly different messages. **Fix**: small `require_optional(module, extra)` helper in utils.py.

- **src/whisperlog/redact.py:73-78** — `redact()` chains Ollama after regex but `RedactionReport.counts` reflects only the regex pass. Misleading. **Fix**: zero counts after Ollama OR add `ollama_used: bool` to the report and document.

- **Cross-file (tests/test_ingest_dedup.py:10-12, tests/test_archive_search.py:11-22, tests/test_transcribe_outputs.py:31-33,47-48)** — Three test files write the same `b"ID3\x00\x00\x00fake"` payload + ingest it. **Fix**: in `tests/conftest.py`, add a `fake_audio_factory` fixture; replace the inline duplications.

### Efficiency

- **src/whisperlog/ingest.py:108** — `src.stat()` is called twice (inside `_recorded_at_from_file` line 89, and again here for `size_bytes`). **Fix**: stat once in `ingest_file`, pass mtime + size into `_recorded_at_from_file`.

- **src/whisperlog/transcribe.py:96, 112** — `get_settings()` re-fetched in `write_outputs` and `transcribe_recording` solely for `whisper_model`. **Fix**: hoist a single `s = get_settings()` and pass `s.whisper_model` (or `s`) through.

- **src/whisperlog/enrich/claude_api.py:51-52, 73** — `Anthropic()` SDK client constructed per `enrich()` call (including a fresh httpx client). Agent loop runs 4 enrichments back-to-back → 4× client construction. **Fix**: `self._cached_client` lazily on the instance; reuse.

- **src/whisperlog/enrich/claude_api.py:103-116** — Manual exponential-backoff `for attempt in range(retries)` loop duplicates what the SDK already does via `Anthropic(max_retries=N)` for the same transient-error set. **Fix**: pass `max_retries=retries` to the SDK constructor; delete the loop.

- **src/whisperlog/archive.py:215-235** — `list_enrichments` always selects `output_text` (potentially tens of KB per row). MCP `list_enrichments` then serializes every row. **Fix**: add `with_text: bool = False` parameter; default omits the body. Provide `get_enrichment_text(id)` for fetch-on-demand.

### Correctness (lower severity)

- **src/whisperlog/mcp_server.py:111-123** — `call_tool` does no error handling; `KeyError`/`ValueError` from `arguments[...]` or `int(...)` will crash the server. **Fix**: wrap dispatch in `try/except (KeyError, ValueError, TypeError) as e: return [TextContent(type="text", text=f"error: {e}")]`.

- **src/whisperlog/mcp_server.py:117** — `get_transcript` returns `{"text": None}` on missing `recording_id` instead of raising. **Fix**: raise `ValueError(f"recording {rid} not found")`; the wrapper above turns it into a graceful tool error.

- **src/whisperlog/redact.py:17-21** — `PHONE_RE` lacks a `(?<!\d)` left-boundary on the local-portion (only the optional country-code group has it); `CREDIT_RE` matches any 13-19-digit run with no Luhn check. Both can over-redact digit-heavy logs. **Fix**: add `(?<!\d)` left-anchor to PHONE_RE; require at least one separator OR a Luhn check on CREDIT_RE.

## Low Severity (skipped — low confidence + low impact)

Skipped per spec: comment styling, naming-convention drift across loggers, individual `_resolve_binary`/`_prompts_dir` corner cases, B008 patterns, tests using `MagicMock` vs `monkeypatch` style, dead `db.close()`, `archive_dir_for` mkdir-as-side-effect.

## Cross-file patterns (summary)

1. Backend `enrich()` tail (audit + log + return) duplicated across 3 backends → unify in `Enricher._finalize`.
2. Two parallel backend dispatch tables (`get_enricher`, `_enricher_for`) → consolidate.
3. `partition_ingest` ad-hoc list-comp in 3 sites → helper.
4. Optional-dep import + raise pattern in 3 sites → `require_optional` helper.
5. Fake-audio test setup in 3 sites → conftest fixture.
6. Day-boundary timezone inconsistency between `ledger.py` write and read paths.
