#!/bin/bash
set -euo pipefail

# bench/run-sequence.sh — Execute a sequence of tasks in a shared workspace
# Usage: ./bench/run-sequence.sh --sequence iterative-features --treatment baseline [--budget 0.50] [--max-turns 30]
#
# Each step gets a fresh Claude instance (no shared context history).
# The workspace persists across steps, so each Claude builds on prior changes.
# After each step, ALL prior steps' acceptance tests are re-run to detect regressions.

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
SEQUENCE=""
TREATMENT=""
BUDGET="0.50"
MAX_TURNS=30

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sequence) SEQUENCE="$2"; shift 2 ;;
    --treatment) TREATMENT="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --max-turns) MAX_TURNS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$SEQUENCE" || -z "$TREATMENT" ]]; then
  echo "Usage: $0 --sequence <name> --treatment <treatment> [--budget <usd>] [--max-turns <n>]" >&2
  exit 2
fi

SEQUENCE_FILE="$BENCH_DIR/sequences/${SEQUENCE}.yaml"
TREATMENT_DIR="$BENCH_DIR/treatments/$TREATMENT"

if [[ ! -f "$SEQUENCE_FILE" ]]; then
  echo "Sequence file not found: $SEQUENCE_FILE" >&2
  exit 1
fi
if [[ ! -d "$TREATMENT_DIR" ]]; then
  echo "Treatment directory not found: $TREATMENT_DIR" >&2
  exit 1
fi

# --- Parse sequence YAML (simple line-based, no yq) ---
SEQ_NAME=""
SEQ_DESC=""
STEPS=()

while IFS= read -r line; do
  if [[ "$line" =~ ^name:[[:space:]]*\"?(.+)\"?$ ]]; then
    SEQ_NAME="${BASH_REMATCH[1]}"
    SEQ_NAME="${SEQ_NAME%\"}"
  elif [[ "$line" =~ ^description:[[:space:]]*\"?(.+)\"?$ ]]; then
    SEQ_DESC="${BASH_REMATCH[1]}"
    SEQ_DESC="${SEQ_DESC%\"}"
  elif [[ "$line" =~ ^[[:space:]]*-[[:space:]]*task:[[:space:]]*\"?(.+)\"?$ ]]; then
    TASK_NAME="${BASH_REMATCH[1]}"
    TASK_NAME="${TASK_NAME%\"}"
    STEPS+=("$TASK_NAME")
  fi
done < "$SEQUENCE_FILE"

NUM_STEPS=${#STEPS[@]}
if [[ $NUM_STEPS -eq 0 ]]; then
  echo "No steps found in sequence: $SEQUENCE_FILE" >&2
  exit 1
fi

# Validate all task directories exist
for step_task in "${STEPS[@]}"; do
  if [[ ! -d "$BENCH_DIR/tasks/$step_task" ]]; then
    echo "Task directory not found for step: $BENCH_DIR/tasks/$step_task" >&2
    exit 1
  fi
done

# Create timestamp and result directory
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULT_DIR="$BENCH_DIR/results/${TIMESTAMP}-seq-${SEQUENCE}-${TREATMENT}"
mkdir -p "$RESULT_DIR"

echo "=== Sequence Run ==="
echo "Sequence:  $SEQUENCE ($SEQ_DESC)"
echo "Treatment: $TREATMENT"
echo "Steps:     $NUM_STEPS (${STEPS[*]})"
echo "Budget:    \$$BUDGET per step"
echo "Results:   $RESULT_DIR"
echo ""

# --- Step 1: Create workspace ONCE ---
WORKSPACE="$(mktemp -d)"
export WORKSPACE
echo "Workspace: $WORKSPACE"

cp -r "$BENCH_DIR/subject/." "$WORKSPACE/"

cd "$WORKSPACE"
git init -q
git add -A
git commit -q -m "Initial commit"

# Write venv python path
BENCH_VENV_PYTHON="$BENCH_DIR/.venv/bin/python3"
mkdir -p "$WORKSPACE/.bdd"
echo "$BENCH_VENV_PYTHON" > "$WORKSPACE/.bdd/venv_python"

# --- Step 2: Apply treatment ONCE ---
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
if grep -q 'context_files:' "$TREATMENT_DIR/treatment.yaml"; then
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

# Skip per_task_context for sequences (not meaningful)

# Run setup script if specified
SETUP_SCRIPT="$(_yaml_val setup_script)"
if [[ -n "$SETUP_SCRIPT" && -f "$TREATMENT_DIR/$SETUP_SCRIPT" ]]; then
  echo "  Running setup script: $SETUP_SCRIPT"
  bash "$TREATMENT_DIR/$SETUP_SCRIPT"
fi

echo ""

# --- Step 3: Step loop ---
SEQUENCE_START_TIME=$(date +%s)
COMPLETED_TASKS=()     # Track completed task names for prior-step testing
COMPLETED_TESTS=()     # Track test file basenames for prior-step testing
ALL_STEPS_PASS=true
CUMULATIVE_PASS_EVERY_STEP=true
TOTAL_TOKENS=0
TOTAL_BUDGET=0
PRIOR_REGRESSIONS=0
STEP_SUMMARIES="["

REGRESSION_BASELINE=22

for ((STEP_IDX=0; STEP_IDX<NUM_STEPS; STEP_IDX++)); do
  STEP_NUM=$((STEP_IDX + 1))
  STEP_TASK="${STEPS[$STEP_IDX]}"
  TASK_DIR="$BENCH_DIR/tasks/$STEP_TASK"
  STEP_DIR="$RESULT_DIR/step-${STEP_NUM}-${STEP_TASK}"
  mkdir -p "$STEP_DIR"

  echo "════════════════════════════════════════"
  echo "Step $STEP_NUM/$NUM_STEPS: $STEP_TASK"
  echo "════════════════════════════════════════"

  # --- Build prompt ---
  PROMPT=""
  if [[ -n "$PRE_PROMPT" ]]; then
    PROMPT="${PRE_PROMPT}\n\n"
  fi
  PROMPT="${PROMPT}$(cat "$TASK_DIR/prompt.md")"

  echo -e "$PROMPT" > "$STEP_DIR/prompt.txt"

  # --- Run claude (fresh instance) ---
  echo "Running claude agent..."
  STEP_START_TIME=$(date +%s)

  cd "$WORKSPACE"
  set +e
  echo -e "$PROMPT" | env -u CLAUDECODE claude -p \
    --output-format stream-json \
    --verbose \
    --max-turns "$MAX_TURNS" \
    --max-budget-usd "$BUDGET" \
    --dangerously-skip-permissions \
    > "$STEP_DIR/agent-output.jsonl" 2>"$STEP_DIR/agent-stderr.txt"
  CLAUDE_EXIT=$?
  set -e

  STEP_END_TIME=$(date +%s)
  STEP_WALL_TIME=$((STEP_END_TIME - STEP_START_TIME))
  echo "Claude finished (exit=$CLAUDE_EXIT, ${STEP_WALL_TIME}s)"

  # --- Generate per-step diff (changes since last commit) ---
  cd "$WORKSPACE"
  git diff > "$STEP_DIR/diff.patch" 2>/dev/null || true
  git diff --stat > "$STEP_DIR/diff-stat.txt" 2>/dev/null || true

  # Include untracked files in diff
  git diff --no-index /dev/null $(git ls-files --others --exclude-standard) >> "$STEP_DIR/diff.patch" 2>/dev/null || true

  FILES_CHANGED=$(git diff --name-only | wc -l | tr -d ' ')
  LINES_ADDED=$(git diff --numstat | awk '{s+=$1} END {print s+0}')
  LINES_REMOVED=$(git diff --numstat | awk '{s+=$2} END {print s+0}')
  UNTRACKED=$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')
  FILES_CHANGED=$((FILES_CHANGED + UNTRACKED))

  # --- Copy this step's test files into workspace ---
  cp "$TASK_DIR"/test_*.py "$WORKSPACE/tests/" 2>/dev/null || true

  # Find the acceptance test for this step
  ACCEPT_TEST=$(ls "$TASK_DIR"/test_*.py 2>/dev/null | head -1)
  ACCEPT_NAME=""
  if [[ -n "$ACCEPT_TEST" ]]; then
    ACCEPT_NAME=$(basename "$ACCEPT_TEST")
  fi

  # --- Run this step's acceptance test ---
  cd "$WORKSPACE"
  set +e
  ACCEPT_PASS=1
  if [[ -n "$ACCEPT_NAME" ]]; then
    python -m pytest "tests/$ACCEPT_NAME" -v --tb=short \
      --junitxml="$STEP_DIR/acceptance-junit.xml" \
      > "$STEP_DIR/acceptance-output.txt" 2>&1
    ACCEPT_PASS=$?
  fi

  # --- Run regression test (test_taskboard.py) ---
  python -m pytest tests/test_taskboard.py -v --tb=short \
    --junitxml="$STEP_DIR/regression-junit.xml" \
    > "$STEP_DIR/regression-output.txt" 2>&1
  REGRESS_PASS=$?

  # --- Run ALL prior steps' acceptance tests (cross-step regression) ---
  PRIOR_PASSED=0
  PRIOR_FAILED=0
  PRIOR_TOTAL=${#COMPLETED_TESTS[@]}

  for ((PI=0; PI<${#COMPLETED_TESTS[@]}; PI++)); do
    PRIOR_TEST="${COMPLETED_TESTS[$PI]}"
    PRIOR_TASK="${COMPLETED_TASKS[$PI]}"
    PRIOR_JUNIT="$STEP_DIR/prior-${PRIOR_TASK}-junit.xml"

    python -m pytest "tests/$PRIOR_TEST" -v --tb=short \
      --junitxml="$PRIOR_JUNIT" \
      > "$STEP_DIR/prior-${PRIOR_TASK}-output.txt" 2>&1
    PRIOR_EXIT=$?
    if [[ $PRIOR_EXIT -eq 0 ]]; then
      PRIOR_PASSED=$((PRIOR_PASSED + 1))
    else
      PRIOR_FAILED=$((PRIOR_FAILED + 1))
      PRIOR_REGRESSIONS=$((PRIOR_REGRESSIONS + 1))
    fi
  done
  set -e

  ACCEPTANCE_PASS="false"
  REGRESSION_PASS="false"
  [[ $ACCEPT_PASS -eq 0 ]] && ACCEPTANCE_PASS="true"
  [[ $REGRESS_PASS -eq 0 ]] && REGRESSION_PASS="true"

  # Cumulative pass: acceptance + regression + all priors pass
  STEP_CUMULATIVE_PASS="false"
  if [[ "$ACCEPTANCE_PASS" == "true" && "$REGRESSION_PASS" == "true" && $PRIOR_FAILED -eq 0 ]]; then
    STEP_CUMULATIVE_PASS="true"
  fi

  if [[ "$ACCEPTANCE_PASS" != "true" ]]; then
    ALL_STEPS_PASS=false
  fi
  if [[ "$STEP_CUMULATIVE_PASS" != "true" ]]; then
    CUMULATIVE_PASS_EVERY_STEP=false
  fi

  echo "  Acceptance: $ACCEPTANCE_PASS | Regression: $REGRESSION_PASS | Priors: $PRIOR_PASSED/$PRIOR_TOTAL OK | Cumulative: $STEP_CUMULATIVE_PASS"

  # --- Extract metrics from stream-json ---
  TOKENS_INPUT=0
  TOKENS_OUTPUT=0
  TOOL_CALLS=0
  API_TURNS=0
  STEP_BUDGET_USED="0.00"

  if [[ -f "$STEP_DIR/agent-output.jsonl" ]]; then
    eval "$(python3 << PYEOF
import json
from collections import defaultdict

input_tokens = 0
output_tokens = 0
tool_calls = 0
api_turns = 0
budget_used = 0.0
tool_breakdown = defaultdict(int)
tool_errors = 0
tool_error_types = defaultdict(int)

with open("$STEP_DIR/agent-output.jsonl") as f:
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
                    name = block.get("name", "unknown")
                    tool_breakdown[name] += 1
        elif t == "user":
            msg = d.get("message", {})
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    if block.get("is_error"):
                        tool_errors += 1
                        content = block.get("content", "")
                        if isinstance(content, list):
                            content = " ".join(
                                b.get("text", "") for b in content
                                if isinstance(b, dict)
                            )
                        prefix = str(content)[:60].strip()
                        if prefix:
                            tool_error_types[prefix] += 1

mcp_tool_calls = sum(v for k, v in tool_breakdown.items() if k.startswith("mcp__bdd__"))
bdd_test_calls = tool_breakdown.get("mcp__bdd__bdd_test", 0)
bdd_motivation_calls = tool_breakdown.get("mcp__bdd__bdd_motivation", 0)
bdd_locate_calls = tool_breakdown.get("mcp__bdd__bdd_locate", 0)
bdd_status_calls = tool_breakdown.get("mcp__bdd__bdd_status", 0)

print(f"TOKENS_INPUT={input_tokens}")
print(f"TOKENS_OUTPUT={output_tokens}")
print(f"TOOL_CALLS={tool_calls}")
print(f"API_TURNS={api_turns}")
print(f"STEP_BUDGET_USED={budget_used:.2f}")
print(f"MCP_TOOL_CALLS={mcp_tool_calls}")
print(f"BDD_TEST_CALLS={bdd_test_calls}")
print(f"BDD_MOTIVATION_CALLS={bdd_motivation_calls}")
print(f"BDD_LOCATE_CALLS={bdd_locate_calls}")
print(f"BDD_STATUS_CALLS={bdd_status_calls}")
print(f"TOOL_ERRORS={tool_errors}")
print(f"TOOL_BREAKDOWN='{json.dumps(dict(tool_breakdown))}'")
print(f"TOOL_ERROR_TYPES='{json.dumps(dict(tool_error_types))}'")
PYEOF
)" 2>/dev/null || eval "TOKENS_INPUT=0; TOKENS_OUTPUT=0; TOOL_CALLS=0; API_TURNS=0; STEP_BUDGET_USED=0.00; MCP_TOOL_CALLS=0; BDD_TEST_CALLS=0; BDD_MOTIVATION_CALLS=0; BDD_LOCATE_CALLS=0; BDD_STATUS_CALLS=0; TOOL_ERRORS=0; TOOL_BREAKDOWN='{}'; TOOL_ERROR_TYPES='{}';"
  fi

  TOKENS_TOTAL=$((TOKENS_INPUT + TOKENS_OUTPUT))
  TOTAL_TOKENS=$((TOTAL_TOKENS + TOKENS_TOTAL))
  TOTAL_BUDGET=$(python3 -c "print(f'{$TOTAL_BUDGET + $STEP_BUDGET_USED:.2f}')")

  # --- Parse JUnit XML ---
  eval "$(python3 << JUNITEOF
import xml.etree.ElementTree as ET
import os

def parse_junit(path):
    if not os.path.isfile(path):
        return 0, 0, 0, 0, 0
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        ts = root if root.tag == "testsuite" else root.find("testsuite")
        if ts is None:
            return 0, 0, 0, 0, 0
        total = int(ts.get("tests", 0))
        failures = int(ts.get("failures", 0))
        errors = int(ts.get("errors", 0))
        skipped = int(ts.get("skipped", 0))
        passed = total - failures - errors - skipped
        return total, passed, failures, skipped, errors
    except Exception:
        return 0, 0, 0, 0, 0

at, ap, af, ask, ae = parse_junit("$STEP_DIR/acceptance-junit.xml")
rt, rp, rf, rsk, re = parse_junit("$STEP_DIR/regression-junit.xml")

print(f"ACCEPTANCE_TOTAL={at}")
print(f"ACCEPTANCE_PASSED={ap}")
print(f"ACCEPTANCE_FAILED={af}")
print(f"ACCEPTANCE_SKIPPED={ask}")
print(f"ACCEPTANCE_ERRORS={ae}")
print(f"REGRESSION_TOTAL={rt}")
print(f"REGRESSION_PASSED={rp}")
print(f"REGRESSION_FAILED={rf}")
print(f"REGRESSION_SKIPPED={rsk}")
print(f"REGRESSION_ERRORS={re}")
JUNITEOF
)" 2>/dev/null || eval "ACCEPTANCE_TOTAL=0; ACCEPTANCE_PASSED=0; ACCEPTANCE_FAILED=0; ACCEPTANCE_SKIPPED=0; ACCEPTANCE_ERRORS=0; REGRESSION_TOTAL=0; REGRESSION_PASSED=0; REGRESSION_FAILED=0; REGRESSION_SKIPPED=0; REGRESSION_ERRORS=0"

  REGRESSION_DELTA=$((REGRESSION_TOTAL - REGRESSION_BASELINE))

  # --- Parse hook lifecycle ---
  HOOK_BEGINS=0
  HOOK_ENDS=0
  HOOK_FAILURES=0
  HOOK_INJECTIONS=0
  HOOK_SKIPS=0
  HOOK_UNIQUE_FACETS=0

  eval "$(python3 << HOOKEOF
import os, re

hook_log = os.path.join("$WORKSPACE", ".bdd", "hook.log")

begins = 0
ends = 0
injections = 0
skips = 0
facet_ids = set()

if os.path.isfile(hook_log):
    with open(hook_log) as f:
        for line in f:
            if " BEGIN " in line:
                begins += 1
            elif " END " in line:
                ends += 1
                if "status=injected" in line:
                    injections += 1
                elif "status=skipped" in line:
                    skips += 1
            m = re.search(r"found \d+ facets: \[([^\]]*)\]", line)
            if m:
                for fid in re.findall(r"'([^']+)'", m.group(1)):
                    facet_ids.add(fid)

failures = max(0, begins - ends)

print(f"HOOK_BEGINS={begins}")
print(f"HOOK_ENDS={ends}")
print(f"HOOK_FAILURES={failures}")
print(f"HOOK_INJECTIONS={injections}")
print(f"HOOK_SKIPS={skips}")
print(f"HOOK_UNIQUE_FACETS={len(facet_ids)}")
HOOKEOF
)" 2>/dev/null || true

  # --- Write per-step metrics.json ---
  cat > "$STEP_DIR/metrics.json" << METRICS_EOF
{
  "task": "$STEP_TASK",
  "treatment": "$TREATMENT",
  "timestamp": "$TIMESTAMP",
  "sequence": "$SEQUENCE",
  "step": $STEP_NUM,
  "total_steps": $NUM_STEPS,
  "acceptance_pass": $ACCEPTANCE_PASS,
  "regression_pass": $REGRESSION_PASS,
  "prior_steps_passed": $PRIOR_PASSED,
  "prior_steps_failed": $PRIOR_FAILED,
  "prior_steps_total": $PRIOR_TOTAL,
  "cumulative_pass": $STEP_CUMULATIVE_PASS,
  "acceptance_total": $ACCEPTANCE_TOTAL,
  "acceptance_passed": $ACCEPTANCE_PASSED,
  "acceptance_failed": $ACCEPTANCE_FAILED,
  "acceptance_skipped": $ACCEPTANCE_SKIPPED,
  "acceptance_errors": $ACCEPTANCE_ERRORS,
  "regression_total": $REGRESSION_TOTAL,
  "regression_passed": $REGRESSION_PASSED,
  "regression_failed": $REGRESSION_FAILED,
  "regression_skipped": $REGRESSION_SKIPPED,
  "regression_errors": $REGRESSION_ERRORS,
  "regression_baseline": $REGRESSION_BASELINE,
  "regression_delta": $REGRESSION_DELTA,
  "tokens_input": $TOKENS_INPUT,
  "tokens_output": $TOKENS_OUTPUT,
  "tokens_total": $TOKENS_TOTAL,
  "tool_calls": $TOOL_CALLS,
  "api_turns": $API_TURNS,
  "wall_time_seconds": $STEP_WALL_TIME,
  "files_changed": $FILES_CHANGED,
  "lines_added": $LINES_ADDED,
  "lines_removed": $LINES_REMOVED,
  "budget_used_usd": $STEP_BUDGET_USED,
  "mcp_tool_calls": $MCP_TOOL_CALLS,
  "bdd_test_calls": $BDD_TEST_CALLS,
  "bdd_motivation_calls": $BDD_MOTIVATION_CALLS,
  "bdd_locate_calls": $BDD_LOCATE_CALLS,
  "bdd_status_calls": $BDD_STATUS_CALLS,
  "tool_errors": $TOOL_ERRORS,
  "tool_error_types": $TOOL_ERROR_TYPES,
  "hook_begins": $HOOK_BEGINS,
  "hook_ends": $HOOK_ENDS,
  "hook_failures": $HOOK_FAILURES,
  "hook_injections": $HOOK_INJECTIONS,
  "hook_skips": $HOOK_SKIPS,
  "hook_unique_facets": $HOOK_UNIQUE_FACETS,
  "tool_breakdown": $TOOL_BREAKDOWN
}
METRICS_EOF

  # --- Commit this step's changes ---
  cd "$WORKSPACE"
  git add -A && git commit -q -m "Step $STEP_NUM: $STEP_TASK" || true

  # --- Generate cumulative diff (initial commit → HEAD) ---
  INITIAL_COMMIT=$(git rev-list --max-parents=0 HEAD)
  git diff "$INITIAL_COMMIT" HEAD > "$STEP_DIR/cumulative-diff.patch" 2>/dev/null || true

  # --- Track completed tasks/tests for prior-step regression ---
  COMPLETED_TASKS+=("$STEP_TASK")
  if [[ -n "$ACCEPT_NAME" ]]; then
    COMPLETED_TESTS+=("$ACCEPT_NAME")
  fi

  # --- Build step summary for aggregate ---
  if [[ $STEP_IDX -gt 0 ]]; then
    STEP_SUMMARIES="${STEP_SUMMARIES},"
  fi
  STEP_SUMMARIES="${STEP_SUMMARIES}{\"step\":$STEP_NUM,\"task\":\"$STEP_TASK\",\"acceptance_pass\":$ACCEPTANCE_PASS,\"regression_pass\":$REGRESSION_PASS,\"prior_steps_passed\":$PRIOR_PASSED,\"prior_steps_failed\":$PRIOR_FAILED,\"cumulative_pass\":$STEP_CUMULATIVE_PASS,\"tokens_total\":$TOKENS_TOTAL,\"wall_time_seconds\":$STEP_WALL_TIME,\"budget_used_usd\":$STEP_BUDGET_USED}"

  echo ""
done

STEP_SUMMARIES="${STEP_SUMMARIES}]"

SEQUENCE_END_TIME=$(date +%s)
TOTAL_WALL_TIME=$((SEQUENCE_END_TIME - SEQUENCE_START_TIME))

# --- Count step pass/fail ---
STEPS_PASSED=0
STEPS_FAILED=0
for ((SI=0; SI<NUM_STEPS; SI++)); do
  STEP_N=$((SI + 1))
  STEP_T="${STEPS[$SI]}"
  SD="$RESULT_DIR/step-${STEP_N}-${STEP_T}"
  if python3 -c "import json; d=json.load(open('$SD/metrics.json')); exit(0 if d.get('acceptance_pass') else 1)" 2>/dev/null; then
    STEPS_PASSED=$((STEPS_PASSED + 1))
  else
    STEPS_FAILED=$((STEPS_FAILED + 1))
  fi
done

# --- Write aggregate metrics.json ---
cat > "$RESULT_DIR/metrics.json" << AGG_EOF
{
  "type": "sequence",
  "sequence": "$SEQUENCE",
  "treatment": "$TREATMENT",
  "timestamp": "$TIMESTAMP",
  "num_steps": $NUM_STEPS,
  "steps": $STEP_SUMMARIES,
  "aggregate": {
    "all_steps_pass": $ALL_STEPS_PASS,
    "cumulative_pass_at_every_step": $CUMULATIVE_PASS_EVERY_STEP,
    "steps_passed": $STEPS_PASSED,
    "steps_failed": $STEPS_FAILED,
    "total_tokens": $TOTAL_TOKENS,
    "total_wall_time_seconds": $TOTAL_WALL_TIME,
    "total_budget_used_usd": $TOTAL_BUDGET,
    "prior_step_regressions": $PRIOR_REGRESSIONS
  }
}
AGG_EOF

# --- Preserve BDD artifacts ---
if [[ -d "$WORKSPACE/.bdd" ]]; then
  mkdir -p "$RESULT_DIR/bdd-artifacts"
  for f in hook.log edit_log.json stop-blocks.log; do
    [[ -f "$WORKSPACE/.bdd/$f" ]] && cp "$WORKSPACE/.bdd/$f" "$RESULT_DIR/bdd-artifacts/"
  done
fi

# Cleanup workspace
rm -rf "$WORKSPACE"

echo "════════════════════════════════════════"
echo "=== Sequence Complete ==="
echo "Sequence:    $SEQUENCE"
echo "Treatment:   $TREATMENT"
echo "Steps:       $STEPS_PASSED/$NUM_STEPS passed"
echo "Cumulative:  $CUMULATIVE_PASS_EVERY_STEP"
echo "Total time:  ${TOTAL_WALL_TIME}s"
echo "Total cost:  \$$TOTAL_BUDGET"
echo "Results:     $RESULT_DIR"
echo ""
cat "$RESULT_DIR/metrics.json"
echo ""
echo "Done."
