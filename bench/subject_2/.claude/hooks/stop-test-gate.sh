#!/usr/bin/env python3
"""stop-test-gate.sh — Stop hook that blocks task completion if regression tests fail.

Called as a Stop hook. Receives JSON on stdin with hook context.
Uses stop_hook_active env var to prevent infinite loops (the hook itself
shouldn't trigger another stop check).
"""

import sys, json, os, subprocess
from datetime import datetime

# --- Read stdin hook payload ---
try:
    hook_input = json.load(sys.stdin)
except Exception:
    hook_input = {}

# Prevent infinite loop: if we're already inside the stop hook, allow stop
if hook_input.get("stop_hook_active") or os.environ.get("STOP_HOOK_ACTIVE"):
    sys.exit(0)

# --- Find project root (look for pyproject.toml) ---
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

test_dir = os.path.join(project_root, "tests")
if not os.path.isdir(test_dir):
    sys.exit(0)

# --- Determine python path ---
venv_python_file = os.path.join(project_root, ".bdd", "venv_python")
python_cmd = "python3"
if os.path.isfile(venv_python_file):
    try:
        with open(venv_python_file) as f:
            p = f.read().strip()
        if p and os.path.isfile(p):
            python_cmd = p
    except Exception:
        pass

# --- Run regression tests ---
env = os.environ.copy()
env["STOP_HOOK_ACTIVE"] = "1"

try:
    result = subprocess.run(
        [python_cmd, "-m", "pytest", "tests/", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
        timeout=120,
    )
except Exception as e:
    # If we can't run tests, don't block
    sys.exit(0)

if result.returncode == 0:
    # All tests pass — allow stop (no output)
    sys.exit(0)

# Tests failed — log the block
log_path = os.path.join(project_root, ".bdd", "stop-blocks.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
with open(log_path, "a") as f:
    f.write(f"{datetime.now().isoformat()} BLOCKED\n")

# Block the stop
output = result.stdout + result.stderr
# Truncate to avoid giant payloads
if len(output) > 3000:
    output = output[:3000] + "\n... (truncated)"

print(json.dumps({
    "decision": "block",
    "reason": f"Regression tests failed. Fix them before finishing:\n\n{output}"
}))
