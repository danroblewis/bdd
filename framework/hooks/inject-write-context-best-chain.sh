#!/usr/bin/env python3
"""inject-write-context-best-chain.sh — Surface the single most relevant BDD motivation chain
after Write/Edit. Scores facets by line proximity, specificity, and test status.
Also logs edits to .bdd/edit_log.json and updates catalog modifications.
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
        log(f"index has {len(forward)} files, catalog has {len(nodes)} nodes")
    except Exception as e:
        log(f"load error: {e}")
        has_index = False

# Find matching file in forward map
rel_path = os.path.relpath(file_path, PROJECT_ROOT) if os.path.isabs(file_path) else file_path
matched = {f: lines for f, lines in forward.items() if rel_path in f or f in rel_path}

if matched:
    log(f"matched {len(matched)} files for {rel_path}")

# Collect facet IDs with line info
facet_lines = {}
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
        except Exception as e:
            log(f"line search failed: {e}")

    if affected_lines:
        for src_file, line_map in matched.items():
            for ls, fids in line_map.items():
                if int(ls) in affected_lines:
                    for fid in fids:
                        facet_lines.setdefault(fid, []).append(int(ls))
    else:
        for src_file, line_map in matched.items():
            for ls, fids in line_map.items():
                for fid in fids:
                    facet_lines.setdefault(fid, []).append(int(ls))

elif matched and tool_name == "Write":
    for src_file, line_map in matched.items():
        for ls, fids in line_map.items():
            for fid in fids:
                facet_lines.setdefault(fid, []).append(int(ls))

all_facet_ids = set(facet_lines.keys())
log(f"found {len(all_facet_ids)} facets: {sorted(all_facet_ids)}")

# Build ancestor chains for logging
chains = []
for fid in sorted(all_facet_ids):
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
    "facets": sorted(all_facet_ids),
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

# Update catalog.json with modification tracking
if all_facet_ids and has_index:
    try:
        for node in nodes:
            if node["id"] in all_facet_ids:
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
        log(f"updated catalog.json with modifications for {sorted(all_facet_ids)}")
    except Exception as e:
        log(f"catalog update error: {e}")

# No facets? Nudge agent
if not all_facet_ids:
    log("no facets matched — nudging agent")
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

# Score facets and pick the best one
mid_line = 0
if affected_lines:
    mid_line = sum(affected_lines) / len(affected_lines)

def score_facet(fid, lines):
    score = 0.0
    node = node_map.get(fid, {})
    if mid_line > 0 and lines:
        avg_line = sum(lines) / len(lines)
        distance = abs(avg_line - mid_line)
        score += max(0, 100 - distance)
    if lines:
        score += max(0, 50 - len(lines))
    status = node.get("status", "untested")
    if status == "failing":
        score += 20
    elif status == "untested":
        score += 10
    return score

scored = [(score_facet(fid, lines), fid) for fid, lines in facet_lines.items()]
scored.sort(reverse=True)
best_fid = scored[0][1]
total_facets = len(all_facet_ids)

log(f"best facet: {best_fid} (score={scored[0][0]:.1f})")

# Build chain for best facet
chain = []
current = node_map.get(best_fid)
while current:
    chain.append(current)
    pid = current.get("parent")
    current = node_map.get(pid) if pid else None
chain.reverse()

# Render as compact markdown
lines_out = [f"--- BDD: What you just changed (best match of {total_facets}) ---"]

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

log(f"END write-hook status=injected file={file_path} facets={total_facets} best={best_fid}")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "\n".join(lines_out)
    }
}))
