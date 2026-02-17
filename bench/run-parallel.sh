#!/bin/bash
set -uo pipefail

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
MAX_JOBS=3
BUDGET="0.50"
LOG_DIR="$BENCH_DIR/results"

TASKS=(001-add-search 002-fix-priority-bug 003-add-tags 004-refactor-store 005-add-due-dates)
TREATMENTS=(baseline claude-md why-how-what full-bdd targeted)

TOTAL=$(( ${#TASKS[@]} * ${#TREATMENTS[@]} ))
echo "Running $TOTAL combinations, $MAX_JOBS concurrently, \$$BUDGET budget each"
echo ""

for task in "${TASKS[@]}"; do
  for treatment in "${TREATMENTS[@]}"; do
    # Wait if we already have MAX_JOBS running
    while [ "$(jobs -r | wc -l)" -ge "$MAX_JOBS" ]; do
      sleep 10
    done
    LOG_FILE="$LOG_DIR/run-${task}-${treatment}.log"
    echo "Starting: $task × $treatment → $LOG_FILE"
    "$BENCH_DIR/run.sh" --task "$task" --treatment "$treatment" --budget "$BUDGET" \
      > "$LOG_FILE" 2>&1 &
  done
done

echo ""
echo "All jobs launched. Waiting for remaining to finish..."
wait
echo "Done. Run: python $BENCH_DIR/analyze.py"
