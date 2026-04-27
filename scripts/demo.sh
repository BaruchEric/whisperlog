#!/usr/bin/env bash
# demo.sh — fully-local pipeline on a CC-licensed sample.
# Pulls a short public-domain speech clip, transcribes it with Whisper,
# and runs the Ollama summarizer.
#
# Prereqs:  uv pip install -e '.'  +  ollama serve  +  ollama pull qwen2.5:7b
set -euo pipefail

SAMPLE_DIR="$(mktemp -d -t ux570-demo-XXXXXX)"
SAMPLE_URL="https://upload.wikimedia.org/wikipedia/commons/4/45/Archive-ugcs-2.ogg"
SAMPLE_FILE="$SAMPLE_DIR/sample.ogg"

echo "Demo workspace: $SAMPLE_DIR"
echo "Downloading CC-licensed sample..."
curl -L -o "$SAMPLE_FILE" "$SAMPLE_URL"

# Convert to mp3 — UX570 produces mp3 natively, demo mirrors the real path.
SAMPLE_MP3="$SAMPLE_DIR/sample.mp3"
ffmpeg -y -i "$SAMPLE_FILE" -codec:a libmp3lame -qscale:a 4 "$SAMPLE_MP3" >/dev/null 2>&1

echo "Transcribing..."
ux570 transcribe "$SAMPLE_MP3"

echo
echo "Searching the archive for the word 'the'..."
ux570 search "the" --limit 3 || true

echo
echo "Running local Ollama summarizer..."
ux570 enrich "$SAMPLE_MP3" --backend ollama --task summarize || {
  echo "Ollama enrichment skipped (is 'ollama serve' running with qwen2.5:7b pulled?)"
}

echo
echo "Demo done. Archive at: $(ux570 config show 2>/dev/null | grep ux570_archive_dir || true)"
