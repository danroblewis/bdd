#!/usr/bin/env python3
"""inject-context-shallow.sh — Goal-level only motivation context for Read hooks.
Used by the progressive-depth treatment: light orientation during exploration.
Shows only the top-level goal(s) that the file serves — no expectations or facets.
"""

import sys, json, os
from datetime import datetime

def find_project_root():
    d = os.getcwd()
    while d != os.path.dirname(d):
        if os.path.isfile(os.path.join(d, "catalog.json")):
            return d
        d = os.path.dirname(d)
    return None

PROJECT_ROOT = find_project_root()
if not PROJECT_ROOT:
    sys.exit(0)

LOGFILE = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", PROJECT_ROOT), ".bdd", "hook.log")
INDEX_FILE = os.path.join(PROJECT_ROOT, ".bdd", "index.json")
CATALOG_FILE = os.path.join(PROJECT_ROOT, "catalog.json")

def log(msg):
    try:
        with open(LOGFILE, "a") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    except Exception:
        pass

if not os.path.isfile(INDEX_FILE):
    sys.exit(0)
if not os.path.isfile(CATALOG_FILE):
    sys.exit(0)

# Read hook input from stdin
hook = json.load(sys.stdin)
tool_name = hook.get("tool_name", "?")
ti = hook.get("tool_input", {})
file_path = ti.get("file_path", "")

log(f"BEGIN read-hook tool={tool_name} file={file_path}")

if tool_name != "Read":
    log(f"END read-hook status=skipped file={file_path} reason=wrong-tool:{tool_name}")
    sys.exit(0)

if not file_path:
    log(f"END read-hook status=skipped file= reason=no-file-path")
    sys.exit(0)

# Skip non-source files
skip_patterns = ("test", "catalog.json", "index.json", ".md", ".toml", ".yaml",
                 ".yml", ".lock", ".json", ".cfg", ".ini", ".bdd/")
for pat in skip_patterns:
    if pat in file_path:
        log(f"END read-hook status=skipped file={file_path} reason=pattern:{pat}")
        sys.exit(0)

# Load index and catalog
try:
    with open(INDEX_FILE) as f:
        index = json.load(f)
    with open(CATALOG_FILE) as f:
        catalog = json.load(f)
except Exception as e:
    log(f"load error: {e}")
    log(f"END read-hook status=skipped file={file_path} reason=load-error")
    sys.exit(0)

forward = index.get("forward", {})
nodes = catalog.get("nodes", [])
node_map = {n["id"]: n for n in nodes}

# Find matching file
rel_path = os.path.relpath(file_path, PROJECT_ROOT) if os.path.isabs(file_path) else file_path
matched = {f: lines for f, lines in forward.items() if rel_path in f or f in rel_path}
if not matched:
    log(f"END read-hook status=skipped file={file_path} reason=no-match")
    sys.exit(0)

# Get line range
offset = ti.get("offset", 0) or 0
limit = ti.get("limit", 0) or 0
start_line = int(offset) if offset else 0
end_line = int(offset) + int(limit) if offset and limit else 0

# Collect facet IDs
facet_ids = set()
for src_file, line_map in matched.items():
    for ls, fids in line_map.items():
        if start_line and end_line:
            if not (start_line <= int(ls) <= end_line):
                continue
        for fid in fids:
            facet_ids.add(fid)

if not facet_ids:
    log(f"END read-hook status=skipped file={file_path} reason=no-facets")
    sys.exit(0)

# Walk up from each facet to find goal(s) — goal-level only
goal_ids = set()
for fid in facet_ids:
    current = node_map.get(fid)
    while current:
        if current["type"] == "goal":
            goal_ids.add(current["id"])
            break
        pid = current.get("parent")
        current = node_map.get(pid) if pid else None

if not goal_ids:
    log(f"END read-hook status=skipped file={file_path} reason=no-goals")
    sys.exit(0)

# Render: goal-level only, one line per goal
lines_out = ["--- BDD: This file serves ---"]
for gid in sorted(goal_ids):
    goal = node_map.get(gid, {})
    lines_out.append(f"**{gid}**: {goal.get('text', '?')}")
lines_out.append("---")

log(f"END read-hook status=injected file={file_path} facets={len(facet_ids)} goals={len(goal_ids)}")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "\n".join(lines_out)
    }
}))
