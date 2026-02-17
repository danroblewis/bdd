#!/bin/bash
set -uo pipefail

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
MAX_JOBS=3
BUDGET="0.50"
LOG_DIR="$BENCH_DIR/results"

TASKS=(001-add-search 002-fix-priority-bug 003-add-tags 004-refactor-store 005-add-due-dates)
TREATMENTS=(planner-agent edit-guard verifier-agent regression-feedback pre-prompt-fine-index prompt-decompose review-before-stop)

TOTAL=$(( ${#TASKS[@]} * ${#TREATMENTS[@]} ))
echo "=== Round 3: Agent/Hook/Skill Treatments ==="
echo "Tasks:      ${TASKS[*]}"
echo "Treatments: ${TREATMENTS[*]}"
echo "Total runs: $TOTAL ($MAX_JOBS concurrent, \$$BUDGET budget each)"
echo "Started:    $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

mkdir -p "$LOG_DIR"

for task in "${TASKS[@]}"; do
  for treatment in "${TREATMENTS[@]}"; do
    while [ "$(jobs -r | wc -l)" -ge "$MAX_JOBS" ]; do
      sleep 10
    done
    LOG_FILE="$LOG_DIR/run-${task}-${treatment}.log"
    echo "[$(date +%H:%M:%S)] Starting: $task × $treatment"
    "$BENCH_DIR/run.sh" --task "$task" --treatment "$treatment" --budget "$BUDGET" \
      > "$LOG_FILE" 2>&1 &
  done
done

echo ""
echo "All $TOTAL jobs launched. Waiting for remaining to finish..."
wait

# Count results
PASSED=0
FAILED=0
for task in "${TASKS[@]}"; do
  for treatment in "${TREATMENTS[@]}"; do
    LOG_FILE="$LOG_DIR/run-${task}-${treatment}.log"
    if grep -q '"acceptance_pass": true' "$LOG_FILE" 2>/dev/null; then
      PASSED=$((PASSED + 1))
    else
      FAILED=$((FAILED + 1))
    fi
  done
done

echo ""
echo "════════════════════════════════════════"
echo "Batch complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Acceptance passed: $PASSED / $TOTAL"
echo "Run analysis with: python3 $BENCH_DIR/analyze.py"
