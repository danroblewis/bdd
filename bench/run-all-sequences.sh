#!/bin/bash
set -uo pipefail

# bench/run-all-sequences.sh — Run all sequence × treatment combinations
# Usage: ./bench/run-all-sequences.sh [--repeat N] [--sequence NAME] [--skip NAME] [--treatment TREATMENT] [--budget USD] [--jobs N]

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
REPEAT=1
FILTER_SEQUENCE=""
SKIP_SEQUENCES=()
FILTER_TREATMENT=""
BUDGET="1.00"
MAX_JOBS=3
LOG_DIR="$BENCH_DIR/results"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repeat) REPEAT="$2"; shift 2 ;;
    --sequence) FILTER_SEQUENCE="$2"; shift 2 ;;
    --skip) SKIP_SEQUENCES+=("$2"); shift 2 ;;
    --treatment) FILTER_TREATMENT="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --jobs) MAX_JOBS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
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

# Discover sequences
SEQUENCES=()
if [[ -d "$BENCH_DIR/sequences" ]]; then
  for f in "$BENCH_DIR"/sequences/*.yaml; do
    [[ -f "$f" ]] || continue
    seq_name="$(basename "$f" .yaml)"
    if [[ -n "$FILTER_SEQUENCE" && "$seq_name" != "$FILTER_SEQUENCE" ]]; then
      continue
    fi
    skip=false
    for s in "${SKIP_SEQUENCES[@]+"${SKIP_SEQUENCES[@]}"}"; do
      if [[ "$seq_name" == "$s" ]]; then skip=true; break; fi
    done
    $skip && continue
    SEQUENCES+=("$seq_name")
  done
fi

if [[ ${#SEQUENCES[@]} -eq 0 ]]; then
  echo "No sequences found in $BENCH_DIR/sequences/" >&2
  exit 1
fi

TOTAL_RUNS=$(( ${#SEQUENCES[@]} * ${#TREATMENTS[@]} * REPEAT ))

echo "=== Bench Run All Sequences ==="
echo "Sequences:  ${SEQUENCES[*]}"
echo "Treatments: ${TREATMENTS[*]}"
echo "Repeat:     $REPEAT"
echo "Budget:     \$$BUDGET per step"
echo "Total runs: $TOTAL_RUNS ($MAX_JOBS concurrent)"
echo ""

mkdir -p "$LOG_DIR"

# --- Launch sequence runs ---
for trial in $(seq 1 "$REPEAT"); do
  for seq_name in "${SEQUENCES[@]}"; do
    for treatment in "${TREATMENTS[@]}"; do
      while [ "$(jobs -r | wc -l)" -ge "$MAX_JOBS" ]; do
        sleep 10
      done
      LOG_FILE="$LOG_DIR/run-seq-${seq_name}-${treatment}.log"
      echo "[$(date +%H:%M:%S)] Starting: $seq_name × $treatment (trial $trial)"
      "$BENCH_DIR/run-sequence.sh" --sequence "$seq_name" --treatment "$treatment" --budget "$BUDGET" \
        > "$LOG_FILE" 2>&1 &
    done
  done
done

echo ""
echo "All $TOTAL_RUNS jobs launched. Waiting for remaining to finish..."
wait

# --- Count results ---
PASSED=0
FAILED=0
for trial in $(seq 1 "$REPEAT"); do
  for seq_name in "${SEQUENCES[@]}"; do
    for treatment in "${TREATMENTS[@]}"; do
      LOG_FILE="$LOG_DIR/run-seq-${seq_name}-${treatment}.log"
      if grep -q '"all_steps_pass": true' "$LOG_FILE" 2>/dev/null; then
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
echo ""

# --- Per-sequence summary ---
printf "%-30s %6s %6s %6s\n" "Sequence" "Pass" "Total" "Pass%"
printf "%-30s %6s %6s %6s\n" "--------" "----" "-----" "-----"
for seq_name in "${SEQUENCES[@]}"; do
  sp=0; st=0
  for trial in $(seq 1 "$REPEAT"); do
    for treatment in "${TREATMENTS[@]}"; do
      st=$((st + 1))
      LOG_FILE="$LOG_DIR/run-seq-${seq_name}-${treatment}.log"
      if grep -q '"all_steps_pass": true' "$LOG_FILE" 2>/dev/null; then
        sp=$((sp + 1))
      fi
    done
  done
  if [ "$st" -gt 0 ]; then pct=$((sp * 100 / st)); else pct=0; fi
  printf "%-30s %6d %6d %5d%%\n" "$seq_name" "$sp" "$st" "$pct"
done
echo ""
if [ "$TOTAL_RUNS" -gt 0 ]; then
  TOTAL_PCT=$((PASSED * 100 / TOTAL_RUNS))
else
  TOTAL_PCT=0
fi
printf "%-30s %6d %6d %5d%%\n" "TOTAL" "$PASSED" "$TOTAL_RUNS" "$TOTAL_PCT"
echo ""
echo "Run analysis with: python $BENCH_DIR/analyze.py"
