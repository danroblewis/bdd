#!/usr/bin/env python3
"""inject-context-narrative.sh — Natural-language motivation context for Read hooks.
Instead of a structured tree, renders each injection as a design note written in prose.
Explains relationships, design rationale, and the dispatch pattern context.
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

log(f"found {len(facet_ids)} facets: {sorted(facet_ids)}")

# Build goal -> expectation -> facets structure
# goal_id -> {goal_node, expectations: {exp_id -> {exp_node, facets: [facet_nodes]}}}
structure = {}
for fid in sorted(facet_ids):
    facet = node_map.get(fid)
    if not facet:
        continue
    # Walk up to find expectation and goal
    exp_node = None
    goal_node = None
    current = node_map.get(facet.get("parent"))
    while current:
        if current["type"] == "expectation" and not exp_node:
            exp_node = current
        elif current["type"] == "goal":
            goal_node = current
            break
        pid = current.get("parent")
        current = node_map.get(pid) if pid else None

    if not goal_node or not exp_node:
        continue

    gid = goal_node["id"]
    eid = exp_node["id"]
    if gid not in structure:
        structure[gid] = {"node": goal_node, "expectations": {}}
    if eid not in structure[gid]["expectations"]:
        structure[gid]["expectations"][eid] = {"node": exp_node, "facets": []}
    structure[gid]["expectations"][eid]["facets"].append(facet)

if not structure:
    log(f"END read-hook status=skipped file={file_path} reason=no-structure")
    sys.exit(0)

# Render as natural-language prose
basename = os.path.basename(rel_path)
module_name = os.path.splitext(basename)[0]

lines_out = ["--- Why this code exists ---"]

for gid, gdata in sorted(structure.items()):
    goal_text = gdata["node"]["text"]
    exp_count = len(gdata["expectations"])

    lines_out.append(f"This module is part of the {module_name} layer. It was designed to {goal_text.lower()} ({gid}).")
    lines_out.append("")

    if exp_count == 1:
        eid, edata = next(iter(gdata["expectations"].items()))
        exp_text = edata["node"]["text"]
        lines_out.append(f"The code you're reading implements: **{exp_text}** ({eid}).")
        for facet in edata["facets"]:
            lines_out.append(f"- {facet['text']}")
    else:
        lines_out.append("The code you're reading implements multiple user expectations:")
        for eid, edata in sorted(gdata["expectations"].items()):
            exp_text = edata["node"]["text"]
            facet_summaries = []
            for facet in edata["facets"]:
                # Extract the function/method name from facet text
                ft = facet["text"]
                if ":" in ft:
                    func_part = ft.split(":")[0] if "." in ft.split(":")[0] else ft[:ft.index(" ")] if " " in ft else ft
                else:
                    func_part = ft[:40]
                facet_summaries.append(func_part)
            lines_out.append(f"- **{exp_text}** ({eid}): {', '.join(facet_summaries)}")

    # Check for architectural expectations
    arch_exps = [e for e in gdata["expectations"].values()
                 if "architecture" in e["node"].get("labels", [])
                 or "dispatch" in e["node"]["text"].lower()
                 or "pattern" in e["node"]["text"].lower()]
    if arch_exps:
        for edata in arch_exps:
            lines_out.append("")
            lines_out.append(f"This follows the project's established pattern ({edata['node']['id']}). "
                           f"Preserve this pattern when adding new functionality.")

lines_out.append("---")

log(f"END read-hook status=injected file={file_path} facets={len(facet_ids)}")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "\n".join(lines_out)
    }
}))
