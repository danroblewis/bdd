#!/usr/bin/env python3
"""inject-write-context-differential.sh — Differential motivation context for Write/Edit hooks.
Tracks what has been shown in .bdd/session_seen.json and only highlights NEW
motivation chains since last injection. Always logs edits and updates catalog.
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
EDIT_LOG_FILE = os.path.join(BDD_DIR, "edit_log.json")
SESSION_FILE = os.path.join(BDD_DIR, "session_seen.json")

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

# Skip non-source files
skip_patterns = ("test", "catalog.json", "index.json", ".md", ".toml", ".yaml",
                 ".yml", ".lock", ".json", ".cfg", ".ini", ".bdd/", ".claude/")
for pat in skip_patterns:
    if pat in file_path:
        log(f"END write-hook status=skipped file={file_path} reason=pattern:{pat}")
        sys.exit(0)

# Load index and catalog
has_index = os.path.isfile(INDEX_FILE) and os.path.isfile(CATALOG_FILE)
forward = {}
nodes = []
node_map = {}
if has_index:
    try:
        with open(INDEX_FILE) as f:
            index = json.load(f)
        with open(CATALOG_FILE) as f:
            catalog = json.load(f)
        forward = index.get("forward", {})
        nodes = catalog.get("nodes", [])
        node_map = {n["id"]: n for n in nodes}
    except Exception as e:
        log(f"load error: {e}")
        has_index = False

# Find matching file
rel_path = os.path.relpath(file_path, PROJECT_ROOT) if os.path.isabs(file_path) else file_path
matched = {f: lines for f, lines in forward.items() if rel_path in f or f in rel_path}

# Collect facet IDs
facet_ids = set()
affected_lines = []

if matched and tool_name == "Edit":
    new_string = ti.get("new_string", "")
    if new_string and os.path.isfile(file_path):
        try:
            with open(file_path) as f:
                file_content = f.readlines()
            new_parts = new_string.split("\n")
            for i, fl in enumerate(file_content, 1):
                stripped = fl.rstrip("\n")
                for nl in new_parts:
                    if nl.strip() and nl.strip() in stripped:
                        affected_lines.append(i)
                        break
        except Exception:
            pass

    if affected_lines:
        for src_file, line_map in matched.items():
            for ls, fids in line_map.items():
                if int(ls) in affected_lines:
                    for fid in fids:
                        facet_ids.add(fid)
    else:
        for src_file, line_map in matched.items():
            for ls, fids in line_map.items():
                for fid in fids:
                    facet_ids.add(fid)

elif matched and tool_name == "Write":
    for src_file, line_map in matched.items():
        for ls, fids in line_map.items():
            for fid in fids:
                facet_ids.add(fid)

# Build ancestor chains for logging
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

# Log to edit_log.json
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
except Exception:
    pass

# Update catalog modifications
if facet_ids and has_index:
    try:
        for node in nodes:
            if node["id"] in facet_ids:
                mods = node.setdefault("modifications", [])
                mods.append({
                    "ts": entry["ts"],
                    "file": rel_path,
                    "tool": tool_name,
                })
                if len(mods) > 50:
                    node["modifications"] = mods[-50:]
        catalog["nodes"] = nodes
        with open(CATALOG_FILE, "w") as f:
            json.dump(catalog, f, indent=2)
            f.write("\n")
    except Exception:
        pass

# No facets? Nudge
if not facet_ids:
    log(f"END write-hook status=unmapped file={file_path}")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"--- BDD: Unmapped file modified ---\n"
                f"You edited {rel_path} but no catalog facet maps to it yet.\n"
                f"If this implements a catalog entry, use bdd_link(facet_id, test_id) "
                f"or bdd_add() to create one.\n"
                f"---"
            )
        }
    }))
    sys.exit(0)

# Load session record for differential tracking
session = {}
try:
    if os.path.isfile(SESSION_FILE):
        with open(SESSION_FILE) as f:
            session = json.load(f)
except (json.JSONDecodeError, ValueError):
    session = {}

# Use write-specific key to track write-hook injections separately
write_key = f"write:{rel_path}"
seen_for_file = set(session.get(write_key, []))
new_facets = facet_ids - seen_for_file
already_shown = facet_ids & seen_for_file

# Update session
session[write_key] = sorted(facet_ids | seen_for_file)
try:
    with open(SESSION_FILE, "w") as f:
        json.dump(session, f, indent=2)
except Exception:
    pass

log(f"differential: {len(new_facets)} new, {len(already_shown)} already shown for write:{rel_path}")

# If all facets already shown, inject a short reminder
if not new_facets:
    log(f"END write-hook status=injected file={file_path} facets=0 (all-seen)")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"--- BDD: {os.path.basename(file_path)} — same {len(already_shown)} facets affected as before (see earlier context) ---"
        }
    }))
    sys.exit(0)

# Build tree from NEW facets only
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
    log(f"END write-hook status=skipped file={file_path} reason=no-chains")
    sys.exit(0)

lines_out = [f"--- BDD: NEW affected motivations for {os.path.basename(file_path)} ({len(new_facets)} new, {len(already_shown)} shown earlier) ---"]

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

log(f"END write-hook status=injected file={file_path} facets={len(new_facets)} new")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "\n".join(lines_out)
    }
}))
