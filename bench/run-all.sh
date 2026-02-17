#!/bin/bash
set -uo pipefail

# bench/run-all.sh — Run all task × treatment combinations
# Usage: ./bench/run-all.sh [--repeat N] [--task TASK] [--treatment TREATMENT] [--budget USD] [--jobs N]

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
REPEAT=1
FILTER_TASK=""
FILTER_TREATMENT=""
BUDGET="1.00"
MAX_JOBS=3
LOG_DIR="$BENCH_DIR/results"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repeat) REPEAT="$2"; shift 2 ;;
    --task) FILTER_TASK="$2"; shift 2 ;;
    --treatment) FILTER_TREATMENT="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --jobs) MAX_JOBS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Discover tasks
TASKS=()
for d in "$BENCH_DIR"/tasks/*/; do
  task_name="$(basename "$d")"
  if [[ -n "$FILTER_TASK" && "$task_name" != "$FILTER_TASK" ]]; then
    continue
  fi
  TASKS+=("$task_name")
done

# Discover treatments
TREATMENTS=()
for d in "$BENCH_DIR"/treatments/*/; do
  treatment_name="$(basename "$d")"
  if [[ -n "$FILTER_TREATMENT" && "$treatment_name" != "$FILTER_TREATMENT" ]]; then
    continue
  fi
  TREATMENTS+=("$treatment_name")
done

TOTAL_RUNS=$(( ${#TASKS[@]} * ${#TREATMENTS[@]} * REPEAT ))
echo "=== Bench Run All ==="
echo "Tasks:      ${TASKS[*]}"
echo "Treatments: ${TREATMENTS[*]}"
echo "Repeat:     $REPEAT"
echo "Budget:     \$$BUDGET per run"
echo "Total runs: $TOTAL_RUNS ($MAX_JOBS concurrent)"
echo ""

mkdir -p "$LOG_DIR"
PASSED=0
FAILED=0
DONE=0

for trial in $(seq 1 "$REPEAT"); do
  for task in "${TASKS[@]}"; do
    for treatment in "${TREATMENTS[@]}"; do
      # Wait if we already have MAX_JOBS running
      while [ "$(jobs -r | wc -l)" -ge "$MAX_JOBS" ]; do
        sleep 10
      done
      LOG_FILE="$LOG_DIR/run-${task}-${treatment}.log"
      echo "[$(date +%H:%M:%S)] Starting: $task × $treatment (trial $trial)"
      "$BENCH_DIR/run.sh" --task "$task" --treatment "$treatment" --budget "$BUDGET" \
        > "$LOG_FILE" 2>&1 &
    done
  done
done

echo ""
echo "All $TOTAL_RUNS jobs launched. Waiting for remaining to finish..."
wait

# Count results
for trial in $(seq 1 "$REPEAT"); do
  for task in "${TASKS[@]}"; do
    for treatment in "${TREATMENTS[@]}"; do
      DONE=$((DONE + 1))
      LOG_FILE="$LOG_DIR/run-${task}-${treatment}.log"
      if grep -q '"acceptance_pass": true' "$LOG_FILE" 2>/dev/null; then
        PASSED=$((PASSED + 1))
      else
        FAILED=$((FAILED + 1))
      fi
    done
  done
done

echo ""
echo "════════════════════════════════════════"
echo "Batch complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Acceptance passed: $PASSED / $TOTAL_RUNS"
echo ""
echo "Run analysis with: python $BENCH_DIR/analyze.py"
