#!/usr/bin/env python3
"""inject-context-differential.sh — Differential motivation context for Read hooks.
Tracks what has been shown in .bdd/session_seen.json and only injects NEW
motivation chains. If all facets for a file have already been shown, injects
a one-liner summary instead. This preserves novelty signal across repeated reads.
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

BDD_DIR = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", PROJECT_ROOT), ".bdd")
LOGFILE = os.path.join(BDD_DIR, "hook.log")
INDEX_FILE = os.path.join(PROJECT_ROOT, ".bdd", "index.json")
CATALOG_FILE = os.path.join(PROJECT_ROOT, "catalog.json")
SESSION_FILE = os.path.join(BDD_DIR, "session_seen.json")

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

# Collect all facet IDs for this read
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

log(f"found {len(facet_ids)} facets: {sorted(facet_ids)}")

# Load session record
session = {}
try:
    if os.path.isfile(SESSION_FILE):
        with open(SESSION_FILE) as f:
            session = json.load(f)
except (json.JSONDecodeError, ValueError):
    session = {}

# Determine which facets are NEW vs already shown
seen_for_file = set(session.get(rel_path, []))
new_facets = facet_ids - seen_for_file
already_shown = facet_ids & seen_for_file

log(f"differential: {len(new_facets)} new, {len(already_shown)} already shown for {rel_path}")

# Update session record (mark all current facets as seen)
session[rel_path] = sorted(facet_ids | seen_for_file)
try:
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    with open(SESSION_FILE, "w") as f:
        json.dump(session, f, indent=2)
except Exception as e:
    log(f"session write error: {e}")

# If all facets already shown, inject a one-liner
if not new_facets:
    log(f"END read-hook status=injected file={file_path} facets=0 (all-seen)")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"--- BDD: {os.path.basename(file_path)} motivations unchanged ({len(already_shown)} facets — see earlier context) ---"
        }
    }))
    sys.exit(0)

# Build deduplicated tree from NEW facet chains only
tree_nodes = {}
tree_roots = set()
for fid in sorted(new_facets):
    chain = []
    current = node_map.get(fid)
    while current:
        chain.append(current)
        pid = current.get("parent")
        current = node_map.get(pid) if pid else None
    chain.reverse()
    for i, n in enumerate(chain):
        if n["id"] not in tree_nodes:
            tree_nodes[n["id"]] = {"node": n, "children": set()}
        if i > 0:
            tree_nodes[chain[i - 1]["id"]]["children"].add(n["id"])
        else:
            tree_roots.add(n["id"])

if not tree_nodes:
    log(f"END read-hook status=skipped file={file_path} reason=no-chains")
    sys.exit(0)

# Render with differential header
lines_out = [f"--- BDD: NEW motivations for {os.path.basename(file_path)} ({len(new_facets)} new, {len(already_shown)} shown earlier) ---"]

def render(nid, indent=0):
    tn = tree_nodes[nid]
    n = tn["node"]
    prefix = "  " * indent
    t = n["type"][0].upper()
    lines_out.append(f'  {prefix}{n["id"]} [{t}] {n["text"]}')
    for cid in sorted(tn["children"]):
        render(cid, indent + 1)

for rid in sorted(tree_roots):
    render(rid)
lines_out.append("---")

log(f"END read-hook status=injected file={file_path} facets={len(new_facets)} new")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "\n".join(lines_out)
    }
}))
