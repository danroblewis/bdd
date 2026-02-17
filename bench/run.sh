#!/bin/bash
set -euo pipefail

# bench/run.sh — Execute one task × treatment pair
# Usage: ./bench/run.sh --task 001-add-search --treatment baseline [--budget 0.50]

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK=""
TREATMENT=""
BUDGET="0.50"
MAX_TURNS=30

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK="$2"; shift 2 ;;
    --treatment) TREATMENT="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --max-turns) MAX_TURNS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$TASK" || -z "$TREATMENT" ]]; then
  echo "Usage: $0 --task <task-name> --treatment <treatment-name> [--budget <usd>]" >&2
  exit 2
fi

TASK_DIR="$BENCH_DIR/tasks/$TASK"
TREATMENT_DIR="$BENCH_DIR/treatments/$TREATMENT"

if [[ ! -d "$TASK_DIR" ]]; then
  echo "Task directory not found: $TASK_DIR" >&2
  exit 1
fi
if [[ ! -d "$TREATMENT_DIR" ]]; then
  echo "Treatment directory not found: $TREATMENT_DIR" >&2
  exit 1
fi

# Create timestamp for this run
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULT_DIR="$BENCH_DIR/results/${TIMESTAMP}-${TASK}-${TREATMENT}"
mkdir -p "$RESULT_DIR"

echo "=== Bench Run ==="
echo "Task:      $TASK"
echo "Treatment: $TREATMENT"
echo "Budget:    \$$BUDGET"
echo "Results:   $RESULT_DIR"
echo ""

# --- Step 1: Create isolated workspace ---
WORKSPACE="$(mktemp -d)"
export WORKSPACE
echo "Workspace: $WORKSPACE"

cp -r "$BENCH_DIR/subject/." "$WORKSPACE/"

# Initialize git in workspace
cd "$WORKSPACE"
git init -q
git add -A
git commit -q -m "Initial commit"

# --- Step 2: Apply treatment ---
echo "Applying treatment: $TREATMENT"

# Parse treatment.yaml (simple line-based parsing, no yq dependency)
_yaml_val() {
  grep "^${1}:" "$TREATMENT_DIR/treatment.yaml" 2>/dev/null | sed 's/^[^:]*: *//' | sed 's/^"//' | sed 's/"$//' | sed 's/^null$//' || true
}

CLAUDE_MD="$(_yaml_val claude_md)"
PRE_PROMPT="$(_yaml_val pre_prompt)"

# Copy CLAUDE.md if specified
if [[ -n "$CLAUDE_MD" && "$CLAUDE_MD" != "null" ]]; then
  cp "$TREATMENT_DIR/$CLAUDE_MD" "$WORKSPACE/CLAUDE.md"
  echo "  Copied CLAUDE.md"
fi

# Copy context files to .claude/rules/
# Parse context_files array from YAML (simple grep for lines starting with "  - ")
CONTEXT_FILES=$(grep '^ *- ' "$TREATMENT_DIR/treatment.yaml" 2>/dev/null | \
  sed -n '/^context_files:/,/^[^ ]/{ /^ *- /s/^ *- *"\?\([^"]*\)"\?/\1/p }' || true)

# Simpler approach: check for context_files entries
if grep -q 'context_files:' "$TREATMENT_DIR/treatment.yaml"; then
  # Extract items after context_files: until next top-level key
  IN_CONTEXT=false
  while IFS= read -r line; do
    if [[ "$line" =~ ^context_files: ]]; then
      IN_CONTEXT=true
      continue
    fi
    if $IN_CONTEXT; then
      if [[ "$line" =~ ^[a-z_] ]]; then
        break
      fi
      if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*\"?(.+)\"?$ ]]; then
        CTX_FILE="${BASH_REMATCH[1]}"
        CTX_FILE="${CTX_FILE%\"}"
        if [[ -n "$CTX_FILE" ]]; then
          mkdir -p "$WORKSPACE/.claude/rules"
          cp "$TREATMENT_DIR/$CTX_FILE" "$WORKSPACE/.claude/rules/$CTX_FILE"
          echo "  Copied context file: $CTX_FILE"
        fi
      fi
    fi
  done < "$TREATMENT_DIR/treatment.yaml"
fi

# Handle per_task_context (for targeted treatment)
if grep -q "per_task_context:" "$TREATMENT_DIR/treatment.yaml" 2>/dev/null; then
  PER_TASK_FILE=$(grep "  $TASK:" "$TREATMENT_DIR/treatment.yaml" 2>/dev/null | \
    sed 's/^[^:]*: *//' | sed 's/^"//' | sed 's/"$//' || true)
  if [[ -n "$PER_TASK_FILE" ]]; then
    mkdir -p "$WORKSPACE/.claude/rules"
    cp "$TREATMENT_DIR/$PER_TASK_FILE" "$WORKSPACE/.claude/rules/$PER_TASK_FILE"
    echo "  Copied per-task context: $PER_TASK_FILE"
  fi
fi

# Run setup script if specified
SETUP_SCRIPT="$(_yaml_val setup_script)"
if [[ -n "$SETUP_SCRIPT" && -f "$TREATMENT_DIR/$SETUP_SCRIPT" ]]; then
  echo "  Running setup script: $SETUP_SCRIPT"
  bash "$TREATMENT_DIR/$SETUP_SCRIPT"
fi

# --- Step 3: Build prompt ---
PROMPT=""
if [[ -n "$PRE_PROMPT" ]]; then
  PROMPT="${PRE_PROMPT}\n\n"
fi
PROMPT="${PROMPT}$(cat "$TASK_DIR/prompt.md")"

# Write prompt to file for reference
echo -e "$PROMPT" > "$WORKSPACE/prompt.txt"
cp "$WORKSPACE/prompt.txt" "$RESULT_DIR/prompt.txt"

# --- Step 4: Run claude ---
echo ""
echo "Running claude agent..."
START_TIME=$(date +%s)

cd "$WORKSPACE"
set +e
echo -e "$PROMPT" | env -u CLAUDECODE claude -p \
  --output-format stream-json \
  --verbose \
  --max-turns "$MAX_TURNS" \
  --max-budget-usd "$BUDGET" \
  --dangerously-skip-permissions \
  > "$RESULT_DIR/agent-output.jsonl" 2>"$RESULT_DIR/agent-stderr.txt"
CLAUDE_EXIT=$?
set -e

END_TIME=$(date +%s)
WALL_TIME=$((END_TIME - START_TIME))

echo "Claude finished (exit=$CLAUDE_EXIT, ${WALL_TIME}s)"

# --- Step 5: Generate diff ---
cd "$WORKSPACE"
git diff > "$RESULT_DIR/diff.patch" 2>/dev/null || true
git diff --stat > "$RESULT_DIR/diff-stat.txt" 2>/dev/null || true

# Count changes
FILES_CHANGED=$(git diff --name-only | wc -l | tr -d ' ')
LINES_ADDED=$(git diff --numstat | awk '{s+=$1} END {print s+0}')
LINES_REMOVED=$(git diff --numstat | awk '{s+=$2} END {print s+0}')

# Also include untracked files
UNTRACKED=$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')
FILES_CHANGED=$((FILES_CHANGED + UNTRACKED))

# --- Step 6: Run acceptance + regression tests ---
echo ""
echo "Running verification..."

set +e
export WORKSPACE
bash "$TASK_DIR/verify.sh" > "$RESULT_DIR/test-output.txt" 2>&1
VERIFY_EXIT=$?
set -e

# Determine pass/fail
# Run acceptance and regression separately to get individual results
set +e
cp "$TASK_DIR"/test_*.py "$WORKSPACE/tests/" 2>/dev/null
cd "$WORKSPACE"

# Find the test file for this task (not test_taskboard.py)
ACCEPT_TEST=$(ls "$TASK_DIR"/test_*.py 2>/dev/null | head -1)
if [[ -n "$ACCEPT_TEST" ]]; then
  ACCEPT_NAME=$(basename "$ACCEPT_TEST")
  python -m pytest "tests/$ACCEPT_NAME" -v > "$RESULT_DIR/acceptance-output.txt" 2>&1
  ACCEPT_PASS=$?
else
  ACCEPT_PASS=1
fi

python -m pytest tests/test_taskboard.py -v > "$RESULT_DIR/regression-output.txt" 2>&1
REGRESS_PASS=$?
set -e

ACCEPTANCE_PASS="false"
REGRESSION_PASS="false"
[[ $ACCEPT_PASS -eq 0 ]] && ACCEPTANCE_PASS="true"
[[ $REGRESS_PASS -eq 0 ]] && REGRESSION_PASS="true"

echo "Acceptance: $ACCEPTANCE_PASS"
echo "Regression: $REGRESSION_PASS"

# --- Step 7: Extract metrics from stream-json ---
# Parse the JSONL output to extract token counts and tool calls
TOKENS_INPUT=0
TOKENS_OUTPUT=0
TOOL_CALLS=0
API_TURNS=0
BUDGET_USED="0.00"

if [[ -f "$RESULT_DIR/agent-output.jsonl" ]]; then
  # Extract all metrics from stream-json in one python pass
  eval "$(python3 << PYEOF
import json

input_tokens = 0
output_tokens = 0
tool_calls = 0
api_turns = 0
budget_used = 0.0

with open("$RESULT_DIR/agent-output.jsonl") as f:
    for line in f:
        try:
            d = json.loads(line)
        except:
            continue
        t = d.get("type", "")
        if t == "result":
            usage = d.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            input_tokens += usage.get("cache_creation_input_tokens", 0)
            input_tokens += usage.get("cache_read_input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            api_turns = d.get("num_turns", 0)
            cost = d.get("total_cost_usd", 0)
            if cost:
                budget_used = float(cost)
        elif t == "assistant":
            msg = d.get("message", {})
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls += 1

print(f"TOKENS_INPUT={input_tokens}")
print(f"TOKENS_OUTPUT={output_tokens}")
print(f"TOOL_CALLS={tool_calls}")
print(f"API_TURNS={api_turns}")
print(f"BUDGET_USED={budget_used:.2f}")
PYEOF
)" 2>/dev/null || eval "TOKENS_INPUT=0; TOKENS_OUTPUT=0; TOOL_CALLS=0; API_TURNS=0; BUDGET_USED=0.00"
fi

TOKENS_TOTAL=$((TOKENS_INPUT + TOKENS_OUTPUT))

# --- Step 8: Write metrics.json ---
cat > "$RESULT_DIR/metrics.json" << METRICS_EOF
{
  "task": "$TASK",
  "treatment": "$TREATMENT",
  "timestamp": "$TIMESTAMP",
  "acceptance_pass": $ACCEPTANCE_PASS,
  "regression_pass": $REGRESSION_PASS,
  "tokens_input": $TOKENS_INPUT,
  "tokens_output": $TOKENS_OUTPUT,
  "tokens_total": $TOKENS_TOTAL,
  "tool_calls": $TOOL_CALLS,
  "api_turns": $API_TURNS,
  "wall_time_seconds": $WALL_TIME,
  "files_changed": $FILES_CHANGED,
  "lines_added": $LINES_ADDED,
  "lines_removed": $LINES_REMOVED,
  "budget_used_usd": $BUDGET_USED
}
METRICS_EOF

echo ""
echo "=== Results ==="
echo "Metrics: $RESULT_DIR/metrics.json"
cat "$RESULT_DIR/metrics.json"

# Cleanup workspace
rm -rf "$WORKSPACE"

echo ""
echo "Done."
