#!/bin/bash
# Setup script for edit-guard treatment
# Installs PreToolUse hook that blocks Edit/Write on source files
# until the agent has read tests/test_taskboard.py.
# Also installs PostToolUse hook on Read that sets the "tests read" flag.

set -euo pipefail
cd "$WORKSPACE"

BENCH_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_PYTHON="$BENCH_ROOT/.venv/bin/python3"

# --- Create hook scripts ---
mkdir -p .claude/hooks

# PreToolUse hook: block Edit/Write on src/ until tests have been read
cat > .claude/hooks/edit-guard.py << 'HOOK_EOF'
#!/usr/bin/env python3
"""PreToolUse hook: block source edits until tests/test_taskboard.py has been read."""
import sys, json, os

hook = json.load(sys.stdin)
tool = hook.get("tool_name", "")
if tool not in ("Edit", "Write"):
    sys.exit(0)

file_path = hook.get("tool_input", {}).get("file_path", "")
if not file_path:
    sys.exit(0)

# Only guard source files
if "/src/" not in file_path and "src/" not in file_path:
    sys.exit(0)

# Check if tests have been read
flag_file = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()), ".bdd", "tests_read")
if os.path.isfile(flag_file):
    sys.exit(0)

# Block the edit
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "You must read tests/test_taskboard.py first to understand expected behavior before editing source files. Read the test file, then try again."
    }
}))
HOOK_EOF

# PostToolUse hook: set flag when test file is read
cat > .claude/hooks/tests-read-flag.py << 'HOOK_EOF'
#!/usr/bin/env python3
"""PostToolUse hook: set flag when tests/test_taskboard.py is read."""
import sys, json, os

hook = json.load(sys.stdin)
if hook.get("tool_name") != "Read":
    sys.exit(0)

file_path = hook.get("tool_input", {}).get("file_path", "")
if "test_taskboard" not in file_path:
    sys.exit(0)

# Set the flag
flag_dir = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()), ".bdd")
os.makedirs(flag_dir, exist_ok=True)
with open(os.path.join(flag_dir, "tests_read"), "w") as f:
    f.write("1")

sys.exit(0)
HOOK_EOF

chmod +x .claude/hooks/edit-guard.py .claude/hooks/tests-read-flag.py

# --- Merge hooks into settings.json ---
python3 -c "
import json
with open('.claude/settings.json') as f: s = json.load(f)
hooks = s.setdefault('hooks', {})
hooks.setdefault('PreToolUse', []).append({
    'matcher': 'Edit|Write',
    'hooks': [{
        'type': 'command',
        'command': '$VENV_PYTHON \"\$CLAUDE_PROJECT_DIR/.claude/hooks/edit-guard.py\" 2>/dev/null || true'
    }]
})
hooks.setdefault('PostToolUse', []).append({
    'matcher': 'Read',
    'hooks': [{
        'type': 'command',
        'command': '$VENV_PYTHON \"\$CLAUDE_PROJECT_DIR/.claude/hooks/tests-read-flag.py\" 2>/dev/null || true'
    }]
})
with open('.claude/settings.json', 'w') as f: json.dump(s, f, indent=2)
"

mkdir -p .bdd

echo "edit-guard initialized: PreToolUse guard + PostToolUse flag hooks"
