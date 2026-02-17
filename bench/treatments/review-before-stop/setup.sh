#!/bin/bash
# Setup script for review-before-stop treatment
# Replaces the basic stop-test-gate with an enhanced version that:
# 1. Runs regression tests (same as before)
# 2. Checks git diff to verify changes touch expected files
# 3. Provides more actionable blocking feedback

set -euo pipefail
cd "$WORKSPACE"

BENCH_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_PYTHON="$BENCH_ROOT/.venv/bin/python3"

# --- Replace the stop hook with an enhanced version ---
mkdir -p .claude/hooks

cat > .claude/hooks/stop-test-gate.sh << HOOK_EOF
#!/usr/bin/env python3
"""Enhanced stop hook — runs regression tests AND reviews completeness."""
import sys, json, os, subprocess
from datetime import datetime

try:
    hook_input = json.load(sys.stdin)
except Exception:
    hook_input = {}

if hook_input.get("stop_hook_active") or os.environ.get("STOP_HOOK_ACTIVE"):
    sys.exit(0)

def find_project_root():
    d = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    while d != os.path.dirname(d):
        if os.path.isfile(os.path.join(d, "pyproject.toml")):
            return d
        d = os.path.dirname(d)
    return None

project_root = find_project_root()
if not project_root:
    sys.exit(0)

test_file = os.path.join(project_root, "tests", "test_taskboard.py")
if not os.path.isfile(test_file):
    sys.exit(0)

python_cmd = "$VENV_PYTHON"
env = os.environ.copy()
env["STOP_HOOK_ACTIVE"] = "1"

# --- Run regression tests ---
try:
    result = subprocess.run(
        [python_cmd, "-m", "pytest", "tests/test_taskboard.py", "-v", "--tb=short"],
        capture_output=True, text=True, cwd=project_root, env=env, timeout=60
    )
except Exception:
    sys.exit(0)

issues = []

if result.returncode != 0:
    output = result.stdout + result.stderr
    if len(output) > 2000:
        output = output[:2000] + "\n... (truncated)"
    issues.append(f"REGRESSION TESTS FAILED:\n{output}")

# --- Check git diff for completeness ---
try:
    diff_result = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True, text=True, cwd=project_root, timeout=10
    )
    changed_files = [f.strip() for f in diff_result.stdout.strip().split("\n") if f.strip()]

    # Also check untracked files
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, cwd=project_root, timeout=10
    )
    new_files = [f.strip() for f in untracked.stdout.strip().split("\n") if f.strip()]
    all_changed = changed_files + new_files

    # Read the prompt to find task keywords
    prompt_file = os.path.join(project_root, "prompt.txt")
    prompt_text = ""
    if os.path.isfile(prompt_file):
        with open(prompt_file) as f:
            prompt_text = f.read().lower()

    # Check if cli.py was modified (most tasks need CLI changes)
    cli_changed = any("cli.py" in f for f in all_changed)
    if not cli_changed and ("command" in prompt_text or "subcommand" in prompt_text):
        issues.append("WARNING: Task mentions adding a command but cli.py was not modified.")

    # Check if display.py was modified when display changes seem needed
    display_changed = any("display.py" in f for f in all_changed)
    display_keywords = ["format", "display", "show", "output", "marker", "overdue", "sort"]
    if not display_changed and any(kw in prompt_text for kw in display_keywords):
        issues.append("WARNING: Task mentions display/formatting but display.py was not modified. Review if display changes are needed.")

except Exception:
    pass

if not issues:
    sys.exit(0)

# Log the block
log_path = os.path.join(project_root, ".bdd", "stop-blocks.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
with open(log_path, "a") as f:
    f.write(f"{datetime.now().isoformat()} BLOCKED ({len(issues)} issues)\n")

reason = "\n\n".join(issues)
print(json.dumps({
    "decision": "block",
    "reason": f"Completion blocked — please fix these issues:\n\n{reason}"
}))
HOOK_EOF

chmod +x .claude/hooks/stop-test-gate.sh

# --- Update settings.json to point to our enhanced stop hook ---
python3 -c "
import json
with open('.claude/settings.json') as f: s = json.load(f)
# Replace the stop hook command to use our enhanced version
hooks = s.get('hooks', {})
for stop_entry in hooks.get('Stop', []):
    for h in stop_entry.get('hooks', []):
        h['command'] = '$VENV_PYTHON \"\$CLAUDE_PROJECT_DIR/.claude/hooks/stop-test-gate.sh\" 2>/dev/null || true'
with open('.claude/settings.json', 'w') as f: json.dump(s, f, indent=2)
"

mkdir -p .bdd

echo "review-before-stop initialized: enhanced stop hook with completeness review"
