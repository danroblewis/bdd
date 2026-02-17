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

# Write venv python path so the Stop hook can find pytest
BENCH_VENV_PYTHON="$BENCH_DIR/.venv/bin/python3"
mkdir -p "$WORKSPACE/.bdd"
echo "$BENCH_VENV_PYTHON" > "$WORKSPACE/.bdd/venv_python"

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
  python -m pytest "tests/$ACCEPT_NAME" -v --tb=short \
    --junitxml="$RESULT_DIR/acceptance-junit.xml" \
    > "$RESULT_DIR/acceptance-output.txt" 2>&1
  ACCEPT_PASS=$?
else
  ACCEPT_PASS=1
fi

python -m pytest tests/test_taskboard.py -v --tb=short \
  --junitxml="$RESULT_DIR/regression-junit.xml" \
  > "$RESULT_DIR/regression-output.txt" 2>&1
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
from collections import defaultdict

input_tokens = 0
output_tokens = 0
tool_calls = 0
api_turns = 0
budget_used = 0.0
tool_breakdown = defaultdict(int)
tool_errors = 0
tool_error_types = defaultdict(int)

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
print(f"BUDGET_USED={budget_used:.2f}")
print(f"MCP_TOOL_CALLS={mcp_tool_calls}")
print(f"BDD_TEST_CALLS={bdd_test_calls}")
print(f"BDD_MOTIVATION_CALLS={bdd_motivation_calls}")
print(f"BDD_LOCATE_CALLS={bdd_locate_calls}")
print(f"BDD_STATUS_CALLS={bdd_status_calls}")
print(f"TOOL_ERRORS={tool_errors}")
print(f"TOOL_BREAKDOWN='{json.dumps(dict(tool_breakdown))}'")
print(f"TOOL_ERROR_TYPES='{json.dumps(dict(tool_error_types))}'")
PYEOF
)" 2>/dev/null || eval "TOKENS_INPUT=0; TOKENS_OUTPUT=0; TOOL_CALLS=0; API_TURNS=0; BUDGET_USED=0.00; MCP_TOOL_CALLS=0; BDD_TEST_CALLS=0; BDD_MOTIVATION_CALLS=0; BDD_LOCATE_CALLS=0; BDD_STATUS_CALLS=0; TOOL_ERRORS=0; TOOL_BREAKDOWN='{}'; TOOL_ERROR_TYPES='{}';"
fi

TOKENS_TOTAL=$((TOKENS_INPUT + TOKENS_OUTPUT))

# --- Step 7b: Parse JUnit XML, stop blocks, and test tampering ---
REGRESSION_BASELINE=22

eval "$(python3 << JUNITEOF
import xml.etree.ElementTree as ET
import os, subprocess

def parse_junit(path):
    """Parse JUnit XML and return (total, passed, failed, skipped, errors)."""
    if not os.path.isfile(path):
        return 0, 0, 0, 0, 0
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        # Handle both <testsuites><testsuite> and bare <testsuite>
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

at, ap, af, ask, ae = parse_junit("$RESULT_DIR/acceptance-junit.xml")
rt, rp, rf, rsk, re = parse_junit("$RESULT_DIR/regression-junit.xml")

# Stop blocks
stop_log = os.path.join("$WORKSPACE", ".bdd", "stop-blocks.log")
stop_blocks = 0
if os.path.isfile(stop_log):
    with open(stop_log) as f:
        stop_blocks = sum(1 for line in f if line.strip())

# Test tampering — check if test_taskboard.py was modified
tampered = False
try:
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True, text=True,
        cwd="$WORKSPACE",
    )
    tampered = "tests/test_taskboard.py" in result.stdout
except Exception:
    pass

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
print(f"STOP_BLOCKS={stop_blocks}")
print(f"REGRESSION_TESTS_MODIFIED={'true' if tampered else 'false'}")
JUNITEOF
)" 2>/dev/null || eval "ACCEPTANCE_TOTAL=0; ACCEPTANCE_PASSED=0; ACCEPTANCE_FAILED=0; ACCEPTANCE_SKIPPED=0; ACCEPTANCE_ERRORS=0; REGRESSION_TOTAL=0; REGRESSION_PASSED=0; REGRESSION_FAILED=0; REGRESSION_SKIPPED=0; REGRESSION_ERRORS=0; STOP_BLOCKS=0; REGRESSION_TESTS_MODIFIED=false"

REGRESSION_DELTA=$((REGRESSION_TOTAL - REGRESSION_BASELINE))

# --- Step 7c: Parse hook lifecycle and edit logs ---
HOOK_BEGINS=0
HOOK_ENDS=0
HOOK_FAILURES=0
HOOK_INJECTIONS=0
HOOK_SKIPS=0
HOOK_UNIQUE_FACETS=0
EDIT_LOG_ENTRIES=0
EDIT_LOG_UNIQUE_FACETS=0
EDIT_LOG_UNIQUE_FILES=0

eval "$(python3 << HOOKEOF
import json, os, re

hook_log = os.path.join("$WORKSPACE", ".bdd", "hook.log")
edit_log_file = os.path.join("$WORKSPACE", ".bdd", "edit_log.json")

# Parse hook.log BEGIN/END markers
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
                    # Extract facet count (informational, not unique IDs)
                elif "status=skipped" in line:
                    skips += 1
            # Collect unique facet IDs from "found N facets: [...]" lines
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

# Parse edit_log.json
entries = 0
edit_facets = set()
edit_files = set()

if os.path.isfile(edit_log_file):
    try:
        with open(edit_log_file) as f:
            edit_log = json.load(f)
        entries = len(edit_log)
        for e in edit_log:
            for fid in e.get("facets", []):
                edit_facets.add(fid)
            fp = e.get("file", "")
            if fp:
                edit_files.add(fp)
    except Exception:
        pass

print(f"EDIT_LOG_ENTRIES={entries}")
print(f"EDIT_LOG_UNIQUE_FACETS={len(edit_facets)}")
print(f"EDIT_LOG_UNIQUE_FILES={len(edit_files)}")
HOOKEOF
)" 2>/dev/null || true

# --- Step 8: Write metrics.json ---
cat > "$RESULT_DIR/metrics.json" << METRICS_EOF
{
  "task": "$TASK",
  "treatment": "$TREATMENT",
  "timestamp": "$TIMESTAMP",
  "acceptance_pass": $ACCEPTANCE_PASS,
  "regression_pass": $REGRESSION_PASS,
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
  "regression_tests_modified": $REGRESSION_TESTS_MODIFIED,
  "stop_blocks": $STOP_BLOCKS,
  "tokens_input": $TOKENS_INPUT,
  "tokens_output": $TOKENS_OUTPUT,
  "tokens_total": $TOKENS_TOTAL,
  "tool_calls": $TOOL_CALLS,
  "api_turns": $API_TURNS,
  "wall_time_seconds": $WALL_TIME,
  "files_changed": $FILES_CHANGED,
  "lines_added": $LINES_ADDED,
  "lines_removed": $LINES_REMOVED,
  "budget_used_usd": $BUDGET_USED,
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
  "edit_log_entries": $EDIT_LOG_ENTRIES,
  "edit_log_unique_facets": $EDIT_LOG_UNIQUE_FACETS,
  "edit_log_unique_files": $EDIT_LOG_UNIQUE_FILES,
  "tool_breakdown": $TOOL_BREAKDOWN
}
METRICS_EOF

echo ""
echo "=== Results ==="
echo "Metrics: $RESULT_DIR/metrics.json"
cat "$RESULT_DIR/metrics.json"

# --- Step 8b: Preserve BDD artifacts ---
if [[ -d "$WORKSPACE/.bdd" ]]; then
  mkdir -p "$RESULT_DIR/bdd-artifacts"
  for f in hook.log edit_log.json stop-blocks.log; do
    [[ -f "$WORKSPACE/.bdd/$f" ]] && cp "$WORKSPACE/.bdd/$f" "$RESULT_DIR/bdd-artifacts/"
  done
fi

# Cleanup workspace
rm -rf "$WORKSPACE"

echo ""
echo "Done."
