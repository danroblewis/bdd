#!/bin/bash
# Setup script for regression-feedback treatment
# Installs PostToolUse hook that auto-runs regression tests after every source edit
# and injects pass/fail results as context.

set -euo pipefail
cd "$WORKSPACE"

BENCH_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_PYTHON="$BENCH_ROOT/.venv/bin/python3"

# --- Create hook script ---
mkdir -p .claude/hooks

cat > .claude/hooks/regression-feedback.py << HOOK_EOF
#!/usr/bin/env python3
"""PostToolUse hook: run regression tests after source edits, inject results."""
import sys, json, os, subprocess

hook = json.load(sys.stdin)
tool = hook.get("tool_name", "")
if tool not in ("Edit", "Write"):
    sys.exit(0)

file_path = hook.get("tool_input", {}).get("file_path", "")
if not file_path:
    sys.exit(0)

# Only run after source file edits
if "/src/" not in file_path and "src/" not in file_path:
    sys.exit(0)

# Find project root
project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

# Run regression tests
try:
    result = subprocess.run(
        ["$VENV_PYTHON", "-m", "pytest", "tests/test_taskboard.py", "-v", "--tb=line", "-q"],
        capture_output=True, text=True, cwd=project_dir, timeout=30
    )
except Exception:
    sys.exit(0)

# Parse results
output = result.stdout + result.stderr
lines = output.strip().split("\n")

# Extract summary line (e.g. "22 passed" or "20 passed, 2 failed")
summary = ""
for line in reversed(lines):
    if "passed" in line or "failed" in line or "error" in line:
        summary = line.strip()
        break

# Extract failing test names
failures = []
for line in lines:
    if "FAILED" in line:
        failures.append(line.strip())

if result.returncode == 0:
    ctx = f"--- Regression Tests: ALL PASSING ({summary}) ---"
else:
    fail_list = "\n".join(f"  {f}" for f in failures[:5])
    ctx = f"--- Regression Tests: FAILING ---\n{summary}\n{fail_list}\n--- Fix these before continuing ---"

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": ctx
    }
}))
HOOK_EOF

chmod +x .claude/hooks/regression-feedback.py

# --- Merge hook into settings.json ---
python3 -c "
import json
with open('.claude/settings.json') as f: s = json.load(f)
hooks = s.setdefault('hooks', {})
hooks.setdefault('PostToolUse', []).append({
    'matcher': 'Edit|Write',
    'hooks': [{
        'type': 'command',
        'command': '$VENV_PYTHON \"\$CLAUDE_PROJECT_DIR/.claude/hooks/regression-feedback.py\" 2>/dev/null || true'
    }]
})
with open('.claude/settings.json', 'w') as f: json.dump(s, f, indent=2)
"

mkdir -p .bdd

echo "regression-feedback initialized: PostToolUse auto-test hook"
