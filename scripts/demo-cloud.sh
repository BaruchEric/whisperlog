#!/usr/bin/env bash
# demo-cloud.sh — opt-in Claude API enrichment on a synthetic transcript.
# Costs real money. See `ux570 stats` afterwards.
#
# Prereqs:  uv pip install -e '.[cloud]'  +  ux570 config set-key anthropic
set -euo pipefail

if ! ux570 config show >/dev/null 2>&1; then
  echo "ux570 not on PATH. Did you run: uv pip install -e '.[cloud]'?"
  exit 1
fi

WORKDIR="$(mktemp -d -t ux570-cloud-demo-XXXXXX)"
TRANSCRIPT="$WORKDIR/transcript.txt"

cat > "$TRANSCRIPT" <<'EOF'
Sarah: I think we should ship the new pricing page next Tuesday. Anyone disagree?
Mike: I want one more round of QA on the checkout flow.
Sarah: OK, let's plan for Thursday then. Mike, can you own QA?
Mike: Yes, I'll have a report by Wednesday end of day.
Sarah: Great. Also we need to update the pricing in the database — that's on me.
EOF

echo "Synthetic transcript at: $TRANSCRIPT"
echo
echo "Running Claude API summarizer (default: claude-sonnet-4-6)..."
ux570 enrich "$TRANSCRIPT" --backend claude-api --task meeting_notes --yes

echo
echo "Spend so far:"
ux570 stats

echo
echo "Audit log location: ~/.ux570/audit.log (no transcript content stored)"
