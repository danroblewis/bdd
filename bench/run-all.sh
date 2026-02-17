#!/bin/bash
set -uo pipefail

# bench/run-all.sh — Run all task × treatment combinations (and optionally sequences)
# Usage: ./bench/run-all.sh [--repeat N] [--task TASK] [--treatment TREATMENT] [--budget USD] [--jobs N]
#        [--include-sequences] [--sequence NAME]

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
REPEAT=1
FILTER_TASK=""
FILTER_TREATMENT=""
BUDGET="1.00"
MAX_JOBS=3
LOG_DIR="$BENCH_DIR/results"
INCLUDE_SEQUENCES=false
FILTER_SEQUENCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repeat) REPEAT="$2"; shift 2 ;;
    --task) FILTER_TASK="$2"; shift 2 ;;
    --treatment) FILTER_TREATMENT="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --jobs) MAX_JOBS="$2"; shift 2 ;;
    --include-sequences) INCLUDE_SEQUENCES=true; shift ;;
    --sequence) FILTER_SEQUENCE="$2"; INCLUDE_SEQUENCES=true; shift 2 ;;
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

# Discover sequences (if enabled)
SEQUENCES=()
if $INCLUDE_SEQUENCES && [[ -d "$BENCH_DIR/sequences" ]]; then
  for f in "$BENCH_DIR"/sequences/*.yaml; do
    [[ -f "$f" ]] || continue
    seq_name="$(basename "$f" .yaml)"
    if [[ -n "$FILTER_SEQUENCE" && "$seq_name" != "$FILTER_SEQUENCE" ]]; then
      continue
    fi
    SEQUENCES+=("$seq_name")
  done
fi

TASK_RUNS=$(( ${#TASKS[@]} * ${#TREATMENTS[@]} * REPEAT ))
SEQ_RUNS=$(( ${#SEQUENCES[@]} * ${#TREATMENTS[@]} * REPEAT ))
TOTAL_RUNS=$((TASK_RUNS + SEQ_RUNS))

echo "=== Bench Run All ==="
echo "Tasks:      ${TASKS[*]}"
echo "Treatments: ${TREATMENTS[*]}"
if [[ ${#SEQUENCES[@]} -gt 0 ]]; then
  echo "Sequences:  ${SEQUENCES[*]}"
fi
echo "Repeat:     $REPEAT"
echo "Budget:     \$$BUDGET per run"
echo "Task runs:  $TASK_RUNS | Sequence runs: $SEQ_RUNS | Total: $TOTAL_RUNS ($MAX_JOBS concurrent)"
echo ""

mkdir -p "$LOG_DIR"
PASSED=0
FAILED=0
DONE=0

# --- Launch single-task runs ---
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

# --- Launch sequence runs ---
for trial in $(seq 1 "$REPEAT"); do
  for seq_name in "${SEQUENCES[@]}"; do
    for treatment in "${TREATMENTS[@]}"; do
      while [ "$(jobs -r | wc -l)" -ge "$MAX_JOBS" ]; do
        sleep 10
      done
      LOG_FILE="$LOG_DIR/run-seq-${seq_name}-${treatment}.log"
      echo "[$(date +%H:%M:%S)] Starting sequence: $seq_name × $treatment (trial $trial)"
      "$BENCH_DIR/run-sequence.sh" --sequence "$seq_name" --treatment "$treatment" --budget "$BUDGET" \
        > "$LOG_FILE" 2>&1 &
    done
  done
done

echo ""
echo "All $TOTAL_RUNS jobs launched. Waiting for remaining to finish..."
wait

# Count single-task results
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

# Count sequence results
SEQ_PASSED=0
SEQ_FAILED=0
for trial in $(seq 1 "$REPEAT"); do
  for seq_name in "${SEQUENCES[@]}"; do
    for treatment in "${TREATMENTS[@]}"; do
      DONE=$((DONE + 1))
      LOG_FILE="$LOG_DIR/run-seq-${seq_name}-${treatment}.log"
      if grep -q '"all_steps_pass": true' "$LOG_FILE" 2>/dev/null; then
        SEQ_PASSED=$((SEQ_PASSED + 1))
      else
        SEQ_FAILED=$((SEQ_FAILED + 1))
      fi
    done
  done
done

echo ""
echo "════════════════════════════════════════"
echo "Batch complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Task acceptance passed: $PASSED / $TASK_RUNS"
if [[ $SEQ_RUNS -gt 0 ]]; then
  echo "Sequence all-steps passed: $SEQ_PASSED / $SEQ_RUNS"
fi
echo ""
echo "Run analysis with: python $BENCH_DIR/analyze.py"
