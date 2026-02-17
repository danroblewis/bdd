#!/usr/bin/env python3
"""inject-context.sh — Surface BDD motivation context after Read tool use.
Reads .bdd/index.json directly (no CLI dependency).
Called as a PostToolUse hook for Read. Receives JSON on stdin.
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
log(f"index has {len(forward)} files, catalog has {len(nodes)} nodes")

# Find matching file in forward map
rel_path = os.path.relpath(file_path, PROJECT_ROOT) if os.path.isabs(file_path) else file_path
matched = {f: lines for f, lines in forward.items() if rel_path in f or f in rel_path}
if not matched:
    log(f"no match for {rel_path}")
    log(f"END read-hook status=skipped file={file_path} reason=no-match")
    sys.exit(0)

log(f"matched {len(matched)} files for {rel_path}")

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
    log("no facets for matched lines")
    log(f"END read-hook status=skipped file={file_path} reason=no-facets")
    sys.exit(0)

log(f"found {len(facet_ids)} facets: {sorted(facet_ids)}")

# Build deduplicated tree from facet chains
node_map = {n["id"]: n for n in nodes}
tree_nodes = {}  # nid -> {node, children set}
tree_roots = set()
for fid in sorted(facet_ids):
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
    log("no chains built")
    log(f"END read-hook status=skipped file={file_path} reason=no-chains")
    sys.exit(0)

log(f"injecting motivation tree ({len(facet_ids)} facets)")
lines = ["--- BDD: This code exists because ---"]

def render(nid, indent=0):
    tn = tree_nodes[nid]
    n = tn["node"]
    prefix = "  " * indent
    t = n["type"][0].upper()
    lines.append(f'  {prefix}{n["id"]} [{t}] {n["text"]}')
    for cid in sorted(tn["children"]):
        render(cid, indent + 1)

for rid in sorted(tree_roots):
    render(rid)
lines.append("---")

log(f"END read-hook status=injected file={file_path} facets={len(facet_ids)}")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "\n".join(lines)
    }
}))
