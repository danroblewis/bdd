#!/bin/bash
# loop.sh — Autonomous BDD implementation loop.
# Phase 0: run tests (establish ground truth, exit if all satisfied)
# Phase 1: Planning agent reads codebase and writes plan.md
# Phase 2: Implementation agent executes plan.md
# Phase 3: run tests (verify, track progress)
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

run_tests() {
  python3 "$SCRIPT_DIR/bdd_server.py" --run-tests "$(pwd)"
}

run_claude() {
  local prompt_file="$1"
  unset CLAUDECODE
  cat "$prompt_file" | claude -p \
    --dangerously-skip-permissions \
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

  # Phase 0: Establish ground truth
  log ""
  log "--- Phase 0: Ground Truth (run tests) ---"
  if run_tests 2>&1 | tee -a "$LOG"; then
    log ""
    log "All expectations satisfied!"
    exit 0
  fi

  # Phase 1: Plan
  log ""
  log "--- Phase 1: Planning ---"
  rm -f plan.md
  run_claude "$SCRIPT_DIR/plan.md"

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

  # Phase 3: Verify
  log ""
  log "--- Phase 3: Verify (run tests) ---"
  if run_tests 2>&1 | tee -a "$LOG"; then
    log ""
    log "All expectations satisfied!"
    exit 0
  fi

  # Brief pause between iterations
  sleep 2
done

log ""
log "Reached max iterations ($MAX_ITERATIONS)."
log "Run bdd_status MCP tool to check progress."
