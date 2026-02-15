#!/bin/bash
# loop.sh — Autonomous BDD implementation loop.
# Spawns fresh claude -p instances to implement one expectation per iteration.
# Usage: ./loop.sh [max_iterations]

set -e
MAX_ITERATIONS="${1:-10}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROGRESS="progress.txt"

# Ensure bdd is on PATH
export PATH="$SCRIPT_DIR:$PATH"

# Initialize progress log
if [ ! -f "$PROGRESS" ]; then
  echo "# BDD Progress Log" > "$PROGRESS"
  echo "Started: $(date)" >> "$PROGRESS"
  echo "" >> "$PROGRESS"
fi

for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "=== Iteration $i of $MAX_ITERATIONS ==="
  echo ""

  # Check if there's work to do
  REMAINING=$(bdd --json status | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['unsatisfied'])")
  if [ "$REMAINING" = "0" ]; then
    echo "All expectations satisfied!"
    bdd status
    exit 0
  fi

  echo "Unsatisfied expectations: $REMAINING"
  echo "Running implementation agent..."

  OUTPUT=$(claude -p < "$SCRIPT_DIR/iteration.md" --dangerously-skip-permissions 2>&1 | tee /dev/stderr) || true

  if echo "$OUTPUT" | grep -q "<bdd>COMPLETE</bdd>"; then
    echo ""
    echo "All expectations satisfied!"
    bdd status
    exit 0
  fi

  # Brief pause between iterations
  sleep 2
done

echo ""
echo "Reached max iterations ($MAX_ITERATIONS)."
echo "Run 'bdd status' to check progress."
bdd status
