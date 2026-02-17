#!/usr/bin/env python3
"""inject-write-context.sh — Surface BDD motivation context after Write/Edit tool use.
Reads .bdd/index.json directly (no CLI dependency).
Called as a PostToolUse hook for Write and Edit. Receives JSON on stdin.
Logs every edit to .bdd/edit_log.json for post-run analysis.
"""

import sys, json, os, subprocess
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
EDIT_LOG_FILE = os.path.join(BDD_DIR, "edit_log.json")

def log(msg):
    try:
        with open(LOGFILE, "a") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] write-hook: {msg}\n")
    except Exception:
        pass

# Read hook input from stdin
hook = json.load(sys.stdin)
tool_name = hook.get("tool_name", "")
ti = hook.get("tool_input", {})
file_path = ti.get("file_path", "")

log(f"BEGIN write-hook tool={tool_name} file={file_path}")

if tool_name not in ("Write", "Edit"):
    log(f"END write-hook status=skipped file={file_path} reason=wrong-tool:{tool_name}")
    sys.exit(0)

if not file_path:
    log(f"END write-hook status=skipped file= reason=no-file-path")
    sys.exit(0)

log(f"{tool_name}: {file_path}")

# Skip non-source files
skip_patterns = ("test", "catalog.json", "index.json", ".md", ".toml", ".yaml",
                 ".yml", ".lock", ".json", ".cfg", ".ini", ".bdd/", ".claude/")
for pat in skip_patterns:
    if pat in file_path:
        log(f"END write-hook status=skipped file={file_path} reason=pattern:{pat}")
        sys.exit(0)

# Load index and catalog — if missing, still log the edit but skip context
has_index = os.path.isfile(INDEX_FILE) and os.path.isfile(CATALOG_FILE)
forward = {}
nodes = []
if has_index:
    try:
        with open(INDEX_FILE) as f:
            index = json.load(f)
        with open(CATALOG_FILE) as f:
            catalog = json.load(f)
        forward = index.get("forward", {})
        nodes = catalog.get("nodes", [])
        log(f"index has {len(forward)} files, catalog has {len(nodes)} nodes")
    except Exception as e:
        log(f"load error: {e}")
        log(f"END write-hook status=skipped file={file_path} reason=load-error")
        has_index = False

# Find matching file in forward map
rel_path = os.path.relpath(file_path, PROJECT_ROOT) if os.path.isabs(file_path) else file_path
matched = {f: lines for f, lines in forward.items() if rel_path in f or f in rel_path}

if matched:
    log(f"matched {len(matched)} files for {rel_path}")

# Collect facet IDs
facet_ids = set()
affected_lines = []

if matched and tool_name == "Edit":
    # For Edit: try to narrow to affected lines by finding new_string in the file
    new_string = ti.get("new_string", "")
    if new_string and os.path.isfile(file_path):
        try:
            with open(file_path) as f:
                file_lines = f.readlines()
            # Find lines that contain parts of new_string
            new_lines = new_string.split("\n")
            for i, fl in enumerate(file_lines, 1):
                stripped = fl.rstrip("\n")
                for nl in new_lines:
                    if nl.strip() and nl.strip() in stripped:
                        affected_lines.append(i)
                        break
        except Exception as e:
            log(f"line search failed: {e}")

    if affected_lines:
        # Narrow to facets on affected lines only
        log(f"narrowing to {len(affected_lines)} affected lines: {affected_lines[:10]}...")
        for src_file, line_map in matched.items():
            for ls, fids in line_map.items():
                if int(ls) in affected_lines:
                    for fid in fids:
                        facet_ids.add(fid)
    else:
        # Fall back to file-level matching
        for src_file, line_map in matched.items():
            for ls, fids in line_map.items():
                for fid in fids:
                    facet_ids.add(fid)

elif matched and tool_name == "Write":
    # For Write: file-level matching (all facets for that file)
    for src_file, line_map in matched.items():
        for ls, fids in line_map.items():
            for fid in fids:
                facet_ids.add(fid)

log(f"found {len(facet_ids)} facets: {sorted(facet_ids)}")

# Build ancestor chains for logging
node_map = {n["id"]: n for n in nodes}
chains = []
for fid in sorted(facet_ids):
    chain_parts = []
    current = node_map.get(fid)
    while current:
        chain_parts.append(current["id"])
        pid = current.get("parent")
        current = node_map.get(pid) if pid else None
    chain_parts.reverse()
    chains.append(" > ".join(chain_parts))

# Always log to edit_log.json
entry = {
    "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    "tool": tool_name,
    "file": rel_path,
    "lines": sorted(set(affected_lines)) if affected_lines else [],
    "facets": sorted(facet_ids),
    "chains": chains,
}

try:
    os.makedirs(os.path.dirname(EDIT_LOG_FILE), exist_ok=True)
    edit_log = []
    if os.path.isfile(EDIT_LOG_FILE):
        try:
            with open(EDIT_LOG_FILE) as f:
                edit_log = json.load(f)
        except (json.JSONDecodeError, ValueError):
            edit_log = []
    edit_log.append(entry)
    with open(EDIT_LOG_FILE, "w") as f:
        json.dump(edit_log, f, indent=2)
    log(f"logged edit to {EDIT_LOG_FILE}")
except Exception as e:
    log(f"edit_log write error: {e}")

# Only inject context if facets were found
if not facet_ids:
    log("no facets matched — silent exit (edit logged)")
    log(f"END write-hook status=skipped file={file_path} reason=no-facets")
    sys.exit(0)

# Build deduplicated tree from facet chains
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
    log(f"END write-hook status=skipped file={file_path} reason=no-chains")
    sys.exit(0)

log(f"injecting motivation tree ({len(facet_ids)} facets)")
lines = ["--- BDD: You modified code that implements ---"]

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

log(f"END write-hook status=injected file={file_path} facets={len(facet_ids)}")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "\n".join(lines)
    }
}))
