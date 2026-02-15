#!/bin/bash
# loop.sh — Autonomous BDD implementation loop (two-phase).
# Phase 1: Planning agent reads codebase and writes plan.md
# Phase 2: Implementation agent executes plan.md
# Usage: ./loop.sh [max_iterations]
# Logs to bdd_loop.log in the current directory.

set -e
MAX_ITERATIONS="${1:-1000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROGRESS="progress.txt"
LOG="bdd_loop.log"

# Ensure bdd is on PATH
export PATH="$SCRIPT_DIR:$PATH"

log() {
  echo "$@" | tee -a "$LOG"
}

run_claude() {
  local prompt_file="$1"
  # (unset CLAUDECODE; cat "$prompt_file" | claude -p \
  #   --dangerously-skip-permissions \
  #   --allow-dangerously-skip-permissions \
  #   --disallowedTools EnterPlanMode \
  #   2>&1) | tee -a "$LOG" || true

  unset CLAUDECODE
  cat "$prompt_file" | claude -p \
    --dangerously-skip-permissions \
    --allow-dangerously-skip-permissions \
    --disallowedTools EnterPlanMode
}

# Initialize progress log
if [ ! -f "$PROGRESS" ]; then
  echo "# BDD Progress Log" > "$PROGRESS"
  echo "Started: $(date)" >> "$PROGRESS"
  echo "" >> "$PROGRESS"
fi

echo "=== BDD Loop started: $(date) ===" >> "$LOG"
echo "Max iterations: $MAX_ITERATIONS" >> "$LOG"
echo "Logging to $LOG"

for i in $(seq 1 $MAX_ITERATIONS); do
  log ""
  log "=========================================="
  log "=== Iteration $i of $MAX_ITERATIONS === $(date)"
  log "=========================================="

  # Check if there's work to do
  REMAINING=$(bdd --json status | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['unsatisfied'])")
  # if [ "$REMAINING" = "0" ]; then
  #   log "All expectations satisfied!"
  #   bdd status | tee -a "$LOG"
  #   exit 0
  # fi

  log "Unsatisfied expectations: $REMAINING"

  # Phase 1: Plan
  log ""
  log "--- Phase 1: Planning ---"
  rm -f plan.md
  run_claude "$SCRIPT_DIR/plan.md"

  # Check if planning agent said we're done
#  if [ -f plan.md ] && head -1 plan.md | grep -q "COMPLETE"; then
#    log ""
#    log "All expectations satisfied!"
#    bdd status | tee -a "$LOG"
#    exit 0
#  fi

  if [ ! -f plan.md ]; then
    log "WARNING: Planning agent did not create plan.md. Skipping iteration."
    continue
  fi

  log ""
  log "--- Plan written to plan.md ---"

  # Phase 2: Execute
  log ""
  log "--- Phase 2: Executing ---"
  run_claude "$SCRIPT_DIR/iteration.md"

  if tail -100 "$LOG" | grep -q "<bdd>COMPLETE</bdd>"; then
    log ""
    log "All expectations satisfied!"
    bdd status | tee -a "$LOG"
    exit 0
  fi

  # Brief pause between iterations
  sleep 2
done

log ""
log "Reached max iterations ($MAX_ITERATIONS)."
log "Run 'bdd status' to check progress."
bdd status | tee -a "$LOG"
