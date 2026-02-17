#!/bin/bash
set -euo pipefail

# bench/run-all.sh — Run all task × treatment combinations
# Usage: ./bench/run-all.sh [--repeat N] [--task TASK] [--treatment TREATMENT] [--budget USD]

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
REPEAT=1
FILTER_TASK=""
FILTER_TREATMENT=""
BUDGET="0.50"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repeat) REPEAT="$2"; shift 2 ;;
    --task) FILTER_TASK="$2"; shift 2 ;;
    --treatment) FILTER_TREATMENT="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
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
echo "Total runs: $TOTAL_RUNS"
echo ""

RUN_NUM=0
PASSED=0
FAILED=0

for trial in $(seq 1 "$REPEAT"); do
  for task in "${TASKS[@]}"; do
    for treatment in "${TREATMENTS[@]}"; do
      RUN_NUM=$((RUN_NUM + 1))
      echo "────────────────────────────────────────"
      echo "[$RUN_NUM/$TOTAL_RUNS] Task: $task | Treatment: $treatment | Trial: $trial"
      echo "────────────────────────────────────────"

      set +e
      "$BENCH_DIR/run.sh" --task "$task" --treatment "$treatment" --budget "$BUDGET"
      EXIT_CODE=$?
      set -e

      if [[ $EXIT_CODE -eq 0 ]]; then
        PASSED=$((PASSED + 1))
      else
        FAILED=$((FAILED + 1))
        echo "WARNING: Run failed with exit code $EXIT_CODE"
      fi
      echo ""
    done
  done
done

echo "════════════════════════════════════════"
echo "All runs complete: $PASSED passed, $FAILED failed out of $TOTAL_RUNS"
echo ""
echo "Run analysis with: python $BENCH_DIR/analyze.py"
