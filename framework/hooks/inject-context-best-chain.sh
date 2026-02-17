#!/usr/bin/env python3
"""inject-context-best-chain.sh — Surface the single most relevant BDD motivation chain after Read.
Scores facets by line proximity, specificity, and test status, then renders only the best match
in a compact markdown format instead of the full tree.
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
    log(f"no index file: {INDEX_FILE}")
    sys.exit(0)
if not os.path.isfile(CATALOG_FILE):
    log(f"no catalog file: {CATALOG_FILE}")
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

log(f"Read: {file_path}")

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
log(f"index has {len(forward)} files, catalog has {len(nodes)} nodes")

# Find matching file in forward map
rel_path = os.path.relpath(file_path, PROJECT_ROOT) if os.path.isabs(file_path) else file_path
matched = {f: lines for f, lines in forward.items() if rel_path in f or f in rel_path}
if not matched:
    log(f"no match for {rel_path}")
    log(f"END read-hook status=skipped file={file_path} reason=no-match")
    sys.exit(0)

log(f"matched {len(matched)} files for {rel_path}")

# Get line range from read parameters
offset = ti.get("offset", 0) or 0
limit = ti.get("limit", 0) or 0
start_line = int(offset) if offset else 0
end_line = int(offset) + int(limit) if offset and limit else 0
# Midpoint of read range for proximity scoring
mid_line = (start_line + end_line) / 2.0 if start_line and end_line else 0

# Collect facet IDs with per-facet line information for scoring
facet_lines = {}  # facet_id -> list of matched line numbers
for src_file, line_map in matched.items():
    for ls, fids in line_map.items():
        line_num = int(ls)
        if start_line and end_line:
            if not (start_line <= line_num <= end_line):
                continue
        for fid in fids:
            facet_lines.setdefault(fid, []).append(line_num)

if not facet_lines:
    log("no facets for matched lines")
    log(f"END read-hook status=skipped file={file_path} reason=no-facets")
    sys.exit(0)

total_facets = len(facet_lines)
log(f"found {total_facets} facets: {sorted(facet_lines.keys())}")

# Score each facet
def score_facet(fid, lines):
    score = 0.0
    node = node_map.get(fid, {})

    # Line proximity: how close is this facet's coverage to the read center?
    if mid_line > 0 and lines:
        avg_line = sum(lines) / len(lines)
        distance = abs(avg_line - mid_line)
        # Closer = higher score (max 100 for exact match)
        score += max(0, 100 - distance)

    # Specificity: facets covering fewer lines are more targeted
    if lines:
        score += max(0, 50 - len(lines))

    # Test status tiebreak: failing > untested > passing
    status = node.get("status", "untested")
    if status == "failing":
        score += 20
    elif status == "untested":
        score += 10
    elif status == "passing":
        score += 0

    return score

scored = [(score_facet(fid, lines), fid) for fid, lines in facet_lines.items()]
scored.sort(reverse=True)
best_fid = scored[0][1]

log(f"best facet: {best_fid} (score={scored[0][0]:.1f})")

# Build the chain for the best facet: facet -> expectation -> goal
chain = []
current = node_map.get(best_fid)
while current:
    chain.append(current)
    pid = current.get("parent")
    current = node_map.get(pid) if pid else None
chain.reverse()  # goal -> expectation -> facet

# Render as compact markdown
lines_out = [f"--- BDD: Why this code exists (best match of {total_facets}) ---"]

for node in chain:
    ntype = node["type"]
    nid = node["id"]
    text = node["text"]
    if ntype == "goal":
        lines_out.append(f"**Goal**: {nid} — {text}")
    elif ntype == "expectation":
        lines_out.append(f"**Expectation**: {nid} — {text}")
    elif ntype == "facet":
        lines_out.append(f"**Implementation**: {nid} — {text}")

if total_facets > 1:
    lines_out.append(f"*{total_facets - 1} more motivation(s) for this file — call bdd_motivation(\"{os.path.basename(file_path)}\") for all*")

lines_out.append("---")

log(f"END read-hook status=injected file={file_path} facets={total_facets} best={best_fid}")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "\n".join(lines_out)
    }
}))
