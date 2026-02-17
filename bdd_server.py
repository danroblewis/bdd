#!/usr/bin/env python3
"""BDD Catalog MCP Server.

Maintains a bidirectional index between source code lines and stakeholder goals.
Agents query the server to get motivation context when reading code, and to find
relevant code when working on a goal.

Usage:
    MCP server:    python3 bdd_server.py /path/to/project
    Run tests:     python3 bdd_server.py --run-tests /path/to/project
"""

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CATALOG_FILE = "catalog.json"
BDD_CONFIG_FILE = "bdd.json"
INDEX_DIR = ".bdd"
INDEX_FILE = os.path.join(INDEX_DIR, "index.json")

VALID_RESULTS_FORMATS = ("junit", "pytest-json", "cargo-json")
VALID_COVERAGE_FORMATS = ("coverage-json", "lcov", "lcov-dir", "cobertura")

TYPE_PREFIX = {"goal": "g", "expectation": "e", "facet": "f"}

# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------

def load_catalog(root):
    path = os.path.join(root, CATALOG_FILE)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_catalog(catalog, root):
    path = os.path.join(root, CATALOG_FILE)
    with open(path, "w") as f:
        json.dump(catalog, f, indent=2)
        f.write("\n")


def load_config(root):
    path = os.path.join(root, BDD_CONFIG_FILE)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_index(root):
    path = os.path.join(root, INDEX_FILE)
    if not os.path.exists(path):
        return {"forward": {}, "reverse": {}, "test_results": {}, "facet_status": {}}
    with open(path) as f:
        return json.load(f)


def save_index(index, root):
    dirpath = os.path.join(root, INDEX_DIR)
    os.makedirs(dirpath, exist_ok=True)
    path = os.path.join(root, INDEX_FILE)
    with open(path, "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")

# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------

def get_node(nodes, node_id):
    for n in nodes:
        if n["id"] == node_id:
            return n
    return None


def get_children(nodes, parent_id):
    return [n for n in nodes if n.get("parent") == parent_id]


def get_ancestor_chain(nodes, node_id):
    chain = []
    current = get_node(nodes, node_id)
    while current:
        chain.append(current)
        pid = current.get("parent")
        current = get_node(nodes, pid) if pid else None
    chain.reverse()
    return chain


def compute_status(nodes, node):
    if node["type"] == "facet":
        return node.get("status", "untested")
    children = get_children(nodes, node["id"])
    if not children:
        return "untested"
    statuses = [compute_status(nodes, c) for c in children]
    if all(s == "passing" for s in statuses):
        return "passing"
    if any(s == "failing" for s in statuses):
        return "failing"
    return "untested"


def next_id(nodes, prefix):
    max_n = 0
    for n in nodes:
        if n["id"].startswith(prefix + "-"):
            try:
                num = int(n["id"].split("-", 1)[1])
                if num > max_n:
                    max_n = num
            except ValueError:
                pass
    return f"{prefix}-{max_n + 1:03d}"


def status_icon(status):
    if status == "passing":
        return "[+]"
    if status == "failing":
        return "[-]"
    return "[ ]"

# ---------------------------------------------------------------------------
# Result parsers
# ---------------------------------------------------------------------------

def parse_junit(filepath):
    results = {}
    tree = ET.parse(filepath)
    root = tree.getroot()
    suites = root.findall(".//testsuite") if root.tag == "testsuites" else [root]
    for suite in suites:
        for tc in suite.findall("testcase"):
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            test_id = f"{classname}::{name}" if classname else name
            if tc.find("failure") is not None or tc.find("error") is not None:
                results[test_id] = "failed"
            elif tc.find("skipped") is not None:
                results[test_id] = "skipped"
            else:
                results[test_id] = "passed"
    return results


def parse_pytest_json(filepath):
    with open(filepath) as f:
        data = json.load(f)
    results = {}
    for test in data.get("tests", []):
        test_id = test.get("nodeid", "")
        outcome = test.get("outcome", "")
        if outcome == "passed":
            results[test_id] = "passed"
        elif outcome in ("failed", "error"):
            results[test_id] = "failed"
        elif outcome == "skipped":
            results[test_id] = "skipped"
    return results


def parse_cargo_json(filepath):
    results = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "test" and event.get("event") in ("ok", "failed", "ignored"):
                name = event.get("name", "")
                ev = event["event"]
                if ev == "ok":
                    results[name] = "passed"
                elif ev == "failed":
                    results[name] = "failed"
                elif ev == "ignored":
                    results[name] = "skipped"
    return results


RESULT_PARSERS = {
    "junit": parse_junit,
    "pytest-json": parse_pytest_json,
    "cargo-json": parse_cargo_json,
}

# ---------------------------------------------------------------------------
# Coverage parsers
# ---------------------------------------------------------------------------

def match_context_to_facets(context_name, test_to_facets):
    """Match a coverage context name to facet IDs using precise matching.
    Tries exact, then normalized, then strips coverage.py context suffixes."""
    # coverage.py contexts look like "tests/test_calc.py::test_add|run"
    # Strip the |run suffix if present
    clean = context_name.split("|")[0].strip()

    # Exact match
    if clean in test_to_facets:
        return test_to_facets[clean]

    # Normalized match
    norm_ctx = normalize_test_id(clean)
    for test_id, facet_ids in test_to_facets.items():
        if normalize_test_id(test_id) == norm_ctx:
            return facet_ids

    # Suffix match (function name after ::)
    if "::" in clean:
        ctx_suffix = clean.rsplit("::", 1)[-1].lower()
        for test_id, facet_ids in test_to_facets.items():
            if "::" in test_id:
                tid_suffix = test_id.rsplit("::", 1)[-1].lower()
                if tid_suffix == ctx_suffix:
                    return facet_ids

    return []


def parse_coverage_json(filepath, root, test_to_facets):
    """Parse coverage.py JSON with per-test contexts. Returns forward map."""
    with open(filepath) as f:
        data = json.load(f)
    forward = {}  # file -> line -> set(facet_ids)
    for src_file, file_data in data.get("files", {}).items():
        contexts = file_data.get("contexts", {})
        if isinstance(contexts, dict):
            for context_name, lines in contexts.items():
                matched_facets = match_context_to_facets(context_name, test_to_facets)
                if matched_facets:
                    rel = os.path.relpath(src_file, root) if os.path.isabs(src_file) else src_file
                    if rel not in forward:
                        forward[rel] = {}
                    for line in lines:
                        ls = str(line)
                        if ls not in forward[rel]:
                            forward[rel][ls] = set()
                        forward[rel][ls].update(matched_facets)
    return forward


def parse_lcov(filepath, root, test_to_facets):
    """Parse LCOV file (whole-suite, no per-test). Returns forward map."""
    all_facet_ids = list({fid for fids in test_to_facets.values() for fid in fids})
    with open(filepath) as f:
        raw = f.read()
    forward = {}
    current_file = None
    for line in raw.splitlines():
        if line.startswith("SF:"):
            current_file = line[3:].strip()
        elif line.startswith("DA:") and current_file:
            parts = line[3:].split(",")
            if len(parts) >= 2 and int(parts[1]) > 0:
                rel = os.path.relpath(current_file, root) if os.path.isabs(current_file) else current_file
                if rel not in forward:
                    forward[rel] = {}
                ls = str(int(parts[0]))
                if ls not in forward[rel]:
                    forward[rel][ls] = set()
                forward[rel][ls].update(all_facet_ids)
        elif line.startswith("end_of_record"):
            current_file = None
    return forward


def parse_cobertura(filepath, root, test_to_facets):
    """Parse Cobertura XML (whole-suite). Returns forward map."""
    all_facet_ids = list({fid for fids in test_to_facets.values() for fid in fids})
    tree = ET.parse(filepath)
    xml_root = tree.getroot()
    forward = {}
    for cls in xml_root.iter("class"):
        filename = cls.get("filename", "")
        if not filename:
            continue
        rel = os.path.relpath(filename, root) if os.path.isabs(filename) else filename
        for line_el in cls.iter("line"):
            line_num = line_el.get("number")
            hits = int(line_el.get("hits", "0"))
            if line_num and hits > 0:
                if rel not in forward:
                    forward[rel] = {}
                ls = str(int(line_num))
                if ls not in forward[rel]:
                    forward[rel][ls] = set()
                forward[rel][ls].update(all_facet_ids)
    return forward


COVERAGE_PARSERS = {
    "coverage-json": parse_coverage_json,
    "lcov": parse_lcov,
    "cobertura": parse_cobertura,
}

# ---------------------------------------------------------------------------
# Test ID matching
# ---------------------------------------------------------------------------

def normalize_test_id(test_id):
    for ext in (".py", ".rs", ".js", ".ts", ".go"):
        test_id = test_id.replace(ext, "")
    test_id = test_id.replace("/", ".").replace("\\", ".")
    return test_id.lower()


def match_test_to_facet(result_ids, facet_test_id):
    if not facet_test_id:
        return None, None
    # Exact
    if facet_test_id in result_ids:
        return facet_test_id, result_ids[facet_test_id]
    # Normalized
    norm_facet = normalize_test_id(facet_test_id)
    for rid, status in result_ids.items():
        if normalize_test_id(rid) == norm_facet:
            return rid, status
    # Suffix
    if "::" in facet_test_id:
        facet_suffix = facet_test_id.rsplit("::", 1)[-1].lower()
        for rid, status in result_ids.items():
            if "::" in rid:
                rid_suffix = rid.rsplit("::", 1)[-1].lower()
                if rid_suffix == facet_suffix:
                    return rid, status
    return None, None

# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------

def build_index(root):
    """Parse results + coverage, match to facets, build forward+reverse maps."""
    catalog = load_catalog(root)
    config = load_config(root)
    if not catalog or not config:
        return None

    nodes = catalog["nodes"]

    # Build test_to_facets map
    test_to_facets = {}
    for n in nodes:
        if n["type"] == "facet" and n.get("test"):
            test_to_facets.setdefault(n["test"], []).append(n["id"])

    # Parse test results
    test_results = {}
    results_file = os.path.join(root, config["results_file"])
    if os.path.exists(results_file):
        parser = RESULT_PARSERS.get(config["results_format"])
        if parser:
            test_results = parser(results_file)

    # Match results to facets, update statuses
    facet_status = {}
    updated = []
    for n in nodes:
        if n["type"] != "facet":
            continue
        if not n.get("test"):
            facet_status[n["id"]] = n.get("status", "untested")
            continue
        matched_id, status = match_test_to_facet(test_results, n["test"])
        if matched_id is not None:
            old = n.get("status", "untested")
            if status == "passed":
                new = "passing"
            elif status == "failed":
                new = "failing"
            else:
                new = old  # skip skipped
            if old != new:
                n["status"] = new
                updated.append({"id": n["id"], "old": old, "new": new})
            facet_status[n["id"]] = n.get("status", "untested")
        else:
            facet_status[n["id"]] = n.get("status", "untested")

    # Save updated statuses
    if updated:
        save_catalog(catalog, root)

    # Parse coverage
    forward = {}
    coverage_file = os.path.join(root, config["coverage_file"])
    cov_format = config["coverage_format"]
    if cov_format == "lcov-dir":
        # Directory of per-test LCOV files
        if os.path.isdir(coverage_file):
            for fname in os.listdir(coverage_file):
                if not fname.endswith(".lcov"):
                    continue
                test_id = fname[:-5].replace("__", "/")
                facet_ids = test_to_facets.get(test_id, [])
                if not facet_ids:
                    for tid, fids in test_to_facets.items():
                        if test_id in tid or tid in test_id:
                            facet_ids.extend(fids)
                if not facet_ids:
                    continue
                fpath = os.path.join(coverage_file, fname)
                partial = parse_lcov(fpath, root, {test_id: facet_ids})
                for f, lines in partial.items():
                    if f not in forward:
                        forward[f] = {}
                    for ls, fids in lines.items():
                        if ls not in forward[f]:
                            forward[f][ls] = set()
                        forward[f][ls].update(fids)
    elif os.path.exists(coverage_file):
        cov_parser = COVERAGE_PARSERS.get(cov_format)
        if cov_parser:
            forward = cov_parser(coverage_file, root, test_to_facets)

    # Convert sets to sorted lists
    forward_clean = {}
    for filepath in sorted(forward):
        forward_clean[filepath] = {}
        for ls in sorted(forward[filepath], key=lambda x: int(x)):
            forward_clean[filepath][ls] = sorted(forward[filepath][ls])

    # Build reverse map
    reverse = {}
    for filepath, lines in forward_clean.items():
        for ls, fids in lines.items():
            for fid in fids:
                if fid not in reverse:
                    reverse[fid] = {}
                if filepath not in reverse[fid]:
                    reverse[fid][filepath] = []
                line_num = int(ls)
                if line_num not in reverse[fid][filepath]:
                    reverse[fid][filepath].append(line_num)

    # Sort reverse line lists
    for fid in reverse:
        for filepath in reverse[fid]:
            reverse[fid][filepath].sort()

    index = {
        "forward": forward_clean,
        "reverse": reverse,
        "test_results": test_results,
        "facet_status": facet_status,
    }

    save_index(index, root)
    return index, updated

# ---------------------------------------------------------------------------
# Project root (set via argv)
# ---------------------------------------------------------------------------

PROJECT_ROOT = None

def get_root():
    if PROJECT_ROOT:
        return PROJECT_ROOT
    return os.getcwd()

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("bdd-catalog")


@mcp.tool()
def bdd_status() -> str:
    """Catalog summary: counts, progress percentage, satisfied/unsatisfied expectations."""
    root = get_root()
    catalog = load_catalog(root)
    if not catalog:
        return json.dumps({"error": "No catalog.json found"})
    nodes = catalog["nodes"]
    goals = [n for n in nodes if n["type"] == "goal"]
    expectations = [n for n in nodes if n["type"] == "expectation"]
    facets = [n for n in nodes if n["type"] == "facet"]
    passing = [f for f in facets if f.get("status") == "passing"]
    failing = [f for f in facets if f.get("status") == "failing"]
    untested = [f for f in facets if f.get("status", "untested") == "untested"]
    total = len(facets)
    coverage = (len(passing) / total * 100) if total > 0 else 0
    satisfied = sum(1 for e in expectations if compute_status(nodes, e) == "passing")
    unsatisfied_exps = [e for e in expectations if compute_status(nodes, e) != "passing"]
    unsatisfied_exps.sort(key=lambda e: e.get("priority", 99))

    lines = [
        f"Goals: {len(goals)}  Expectations: {len(expectations)}  Facets: {total}",
        f"Passing: {len(passing)}  Failing: {len(failing)}  Untested: {len(untested)}",
        f"Coverage: {round(coverage, 1)}%  Satisfied: {satisfied}/{len(expectations)}",
    ]

    if unsatisfied_exps:
        lines.append("")
        lines.append(f"Top unsatisfied ({len(unsatisfied_exps)} total):")
        for exp in unsatisfied_exps[:10]:
            parent = get_node(nodes, exp.get("parent"))
            prefix = f"{parent['id']}" if parent else "?"
            status = compute_status(nodes, exp)
            lines.append(f"  {exp['id']} [{status}] {exp['text']}  ({prefix})")
            for f in get_children(nodes, exp["id"]):
                if f.get("status", "untested") != "passing":
                    lines.append(f"    {f['id']} [{f.get('status', 'untested')}] {f['text']}")

    return "\n".join(lines)


@mcp.tool()
def bdd_next() -> str:
    """Next unsatisfied expectation to work on, with its facets and parent goal context."""
    root = get_root()
    catalog = load_catalog(root)
    if not catalog:
        return json.dumps({"error": "No catalog.json found"})
    nodes = catalog["nodes"]
    expectations = [n for n in nodes if n["type"] == "expectation"]
    unsatisfied = [e for e in expectations if compute_status(nodes, e) != "passing"]
    unsatisfied.sort(key=lambda e: e.get("priority", 99))
    if not unsatisfied:
        return json.dumps({"all_satisfied": True, "message": "All expectations satisfied!"})
    exp = unsatisfied[0]
    facets = get_children(nodes, exp["id"])
    parent = get_node(nodes, exp.get("parent"))
    # Format readable output
    lines = []
    if parent:
        lines.append(f"Goal: {parent['id']} — {parent['text']}")
        lines.append("")
    lines.append(f"Expectation: {exp['id']} — {exp['text']}")
    if exp.get("priority"):
        lines.append(f"Priority: {exp['priority']}")
    lines.append("")
    if facets:
        lines.append("Facets:")
        for f in facets:
            icon = status_icon(f.get("status", "untested"))
            test = f" (test: {f['test']})" if f.get("test") else ""
            lines.append(f"  {icon} {f['id']} — {f['text']}{test}")
    else:
        lines.append("No facets yet — decompose this expectation into testable facets.")
    return "\n".join(lines)


@mcp.tool()
def bdd_tree(node_id: str = "", status_filter: str = "", max_depth: int = 0) -> str:
    """Catalog hierarchy with statuses. Filterable to avoid overwhelming output.

    Args:
        node_id: Show only the subtree under this node (e.g. "g-001", "e-005"). Empty = all.
        status_filter: Filter branches by status. "unsatisfied" hides fully-passing branches. "failing" shows only branches with failures. Empty = all.
        max_depth: Maximum tree depth to show (1=goals only, 2=goals+expectations, 3=all). 0 = unlimited.
    """
    root = get_root()
    catalog = load_catalog(root)
    if not catalog:
        return json.dumps({"error": "No catalog.json found"})
    nodes = catalog["nodes"]

    if node_id:
        target = get_node(nodes, node_id)
        if not target:
            return f"Node '{node_id}' not found"
        roots = [target]
    else:
        roots = [n for n in nodes if n.get("parent") is None]
    roots.sort(key=lambda n: n.get("priority", 99))

    lines = []

    def should_show(node):
        if not status_filter:
            return True
        s = compute_status(nodes, node)
        if status_filter == "unsatisfied":
            return s != "passing"
        if status_filter == "failing":
            return s == "failing"
        if status_filter == "untested":
            return s == "untested"
        if status_filter == "passing":
            return s == "passing"
        return True

    def print_tree(node, indent=0, depth=1):
        if max_depth and depth > max_depth:
            return
        status = compute_status(nodes, node)
        icon = status_icon(status)
        prefix = "  " * indent
        type_label = node["type"][0].upper()
        lines.append(f"{prefix}{icon} {node['id']} [{type_label}] {node['text']}")
        children = get_children(nodes, node["id"])
        children.sort(key=lambda n: n.get("priority", 99))
        for c in children:
            if should_show(c):
                print_tree(c, indent + 1, depth + 1)

    if not roots:
        return "Catalog is empty. Use bdd_add to get started."
    for r in roots:
        if should_show(r):
            print_tree(r)

    if not lines:
        return f"No nodes match filter (status_filter={status_filter!r})"
    return "\n".join(lines)


@mcp.tool()
def bdd_motivation(file: str, start_line: int = 0, end_line: int = 0) -> str:
    """Why does this code exist? Returns goal->expectation->facet chains for lines in a file.

    Args:
        file: Source file path (relative to project root)
        start_line: Start of line range (0 = all lines)
        end_line: End of line range (0 = all lines)
    """
    root = get_root()
    index = load_index(root)
    catalog = load_catalog(root)
    if not catalog:
        return json.dumps({"error": "No catalog.json found"})
    nodes = catalog["nodes"]
    fwd = index.get("forward", {})

    # Find matching files (substring match)
    matched_files = {f: lines for f, lines in fwd.items() if file in f}
    if not matched_files:
        return f"No catalog entries related to {file}"

    facet_ids = set()
    for src_file, line_map in matched_files.items():
        for ls, fids in line_map.items():
            if start_line and end_line:
                if not (start_line <= int(ls) <= end_line):
                    continue
            for fid in fids:
                facet_ids.add(fid)

    if not facet_ids:
        return f"No catalog entries for {file}" + (f" lines {start_line}-{end_line}" if start_line else "")

    # Build a tree from the facet chains, deduplicating shared ancestors
    # tree_nodes[node_id] = {children: set(), node: dict}
    tree_nodes = {}
    tree_roots = set()
    for fid in sorted(facet_ids):
        chain = get_ancestor_chain(nodes, fid)
        for i, n in enumerate(chain):
            if n["id"] not in tree_nodes:
                tree_nodes[n["id"]] = {"node": n, "children": set()}
            if i > 0:
                tree_nodes[chain[i - 1]["id"]]["children"].add(n["id"])
            else:
                tree_roots.add(n["id"])

    lines = ["--- This code exists because ---"]

    def render(nid, indent=0):
        tn = tree_nodes[nid]
        n = tn["node"]
        prefix = "  " * indent
        type_label = n["type"][0].upper()
        lines.append(f"  {prefix}{n['id']} [{type_label}] {n['text']}")
        for cid in sorted(tn["children"]):
            render(cid, indent + 1)

    for rid in sorted(tree_roots):
        render(rid)
    lines.append("---")
    return "\n".join(lines)


@mcp.tool()
def bdd_locate(node_id: str) -> str:
    """Where is this implemented? Returns files and line ranges for a facet or expectation.

    Args:
        node_id: Node ID (e.g. f-001, e-001)
    """
    root = get_root()
    index = load_index(root)
    catalog = load_catalog(root)
    if not catalog:
        return json.dumps({"error": "No catalog.json found"})
    nodes = catalog["nodes"]
    node = get_node(nodes, node_id)
    if not node:
        return f"Node '{node_id}' not found"

    reverse = index.get("reverse", {})

    # For expectations/goals, collect all descendant facet IDs
    if node["type"] == "facet":
        target_ids = [node_id]
    else:
        target_ids = []

        def collect_facets(nid):
            n = get_node(nodes, nid)
            if not n:
                return
            if n["type"] == "facet":
                target_ids.append(nid)
            for child in get_children(nodes, nid):
                collect_facets(child["id"])

        collect_facets(node_id)

    if not target_ids:
        return f"No facets found under {node_id}"

    # Gather all files and lines
    file_lines = {}  # file -> set(lines)
    for fid in target_ids:
        if fid in reverse:
            for filepath, lines in reverse[fid].items():
                if filepath not in file_lines:
                    file_lines[filepath] = set()
                file_lines[filepath].update(lines)

    if not file_lines:
        return f"No coverage data for {node_id}. Run bdd_test first to build the index."

    result_lines = [f"Implementation of {node_id} ({node['text']}):"]
    for filepath in sorted(file_lines):
        lines = sorted(file_lines[filepath])
        # Compress into ranges
        ranges = []
        start = lines[0]
        end = lines[0]
        for ln in lines[1:]:
            if ln == end + 1:
                end = ln
            else:
                ranges.append((start, end))
                start = ln
                end = ln
        ranges.append((start, end))
        range_strs = [f"{s}-{e}" if s != e else str(s) for s, e in ranges]
        result_lines.append(f"  {filepath}: lines {', '.join(range_strs)}")

    return "\n".join(result_lines)


@mcp.tool()
def bdd_add(node_type: str, text: str, parent: str = "", priority: int = 1, labels: str = "") -> str:
    """Add a goal, expectation, or facet to the catalog.

    Args:
        node_type: One of: goal, expectation, facet
        text: Description of the node
        parent: Parent node ID (required for expectation/facet unless only one candidate exists)
        priority: Priority (lower = higher priority, default 1)
        labels: Comma-separated labels (e.g. "setup,core")
    """
    root = get_root()
    catalog = load_catalog(root)
    if not catalog:
        catalog = {"version": 1, "nodes": []}
    nodes = catalog["nodes"]

    if node_type not in TYPE_PREFIX:
        return f"Error: node_type must be one of: goal, expectation, facet"

    parent_id = parent if parent else None

    # Auto-resolve parent
    if not parent_id:
        if node_type == "expectation":
            goals = [n for n in nodes if n["type"] == "goal"]
            if len(goals) == 1:
                parent_id = goals[0]["id"]
            elif len(goals) > 1:
                return "Error: Multiple goals exist. Specify parent."
        elif node_type == "facet":
            expectations = [n for n in nodes if n["type"] == "expectation"]
            if len(expectations) == 1:
                parent_id = expectations[0]["id"]
            elif len(expectations) > 1:
                return "Error: Multiple expectations exist. Specify parent."

    # Validate parent exists
    if parent_id and not get_node(nodes, parent_id):
        return f"Error: Parent '{parent_id}' not found."

    new_id = next_id(nodes, TYPE_PREFIX[node_type])
    node = {
        "id": new_id,
        "type": node_type,
        "text": text,
        "parent": parent_id,
    }

    if node_type in ("goal", "expectation"):
        node["priority"] = priority
        node["labels"] = [l.strip() for l in labels.split(",") if l.strip()] if labels else []
    elif node_type == "facet":
        node["test"] = None
        node["status"] = "untested"

    nodes.append(node)
    save_catalog(catalog, root)
    result = f"Added {node_type}: {new_id} — {text}"
    if parent_id:
        result += f"\n  Parent: {parent_id}"
    return result


@mcp.tool()
def bdd_link(facet_id: str, test_id: str) -> str:
    """Connect a facet to a test identifier.

    Args:
        facet_id: Facet ID (e.g. f-001)
        test_id: Test identifier (e.g. tests/test_calc.py::test_add)
    """
    root = get_root()
    catalog = load_catalog(root)
    if not catalog:
        return "Error: No catalog.json found"
    nodes = catalog["nodes"]
    node = get_node(nodes, facet_id)
    if not node:
        return f"Error: Node '{facet_id}' not found."
    if node["type"] != "facet":
        return f"Error: '{facet_id}' is a {node['type']}, not a facet."

    node["test"] = test_id
    save_catalog(catalog, root)
    return f"Linked {facet_id} -> {test_id}"


@mcp.tool()
def bdd_test() -> str:
    """Run tests, parse results and coverage, rebuild the index, return summary."""
    root = get_root()
    config = load_config(root)
    if not config:
        return json.dumps({"error": "No bdd.json found"})

    catalog = load_catalog(root)
    if not catalog:
        return json.dumps({"error": "No catalog.json found"})

    # Validate config
    for key in ("test_command", "results_format", "results_file", "coverage_format", "coverage_file"):
        if key not in config:
            return json.dumps({"error": f"bdd.json missing required field: {key}"})

    # Run test command
    test_cmd = config["test_command"]
    result = subprocess.run(test_cmd, shell=True, cwd=root,
                            capture_output=True, text=True)
    test_exit_code = result.returncode

    # Build index (parses results, coverage, updates facet statuses)
    build_result = build_index(root)
    if build_result is None:
        return json.dumps({"error": "Failed to build index"})

    index, updated = build_result

    # Compute summary
    catalog = load_catalog(root)  # reload after updates
    nodes = catalog["nodes"]
    facets = [n for n in nodes if n["type"] == "facet"]
    passing = [f for f in facets if f.get("status") == "passing"]
    failing = [f for f in facets if f.get("status") == "failing"]
    untested = [f for f in facets if f.get("status", "untested") == "untested"]
    expectations = [n for n in nodes if n["type"] == "expectation"]
    satisfied = sum(1 for e in expectations if compute_status(nodes, e) == "passing")
    all_satisfied = satisfied == len(expectations) and len(expectations) > 0

    return json.dumps({
        "test_exit_code": test_exit_code,
        "results_parsed": len(index.get("test_results", {})),
        "facets_updated": updated,
        "passing": len(passing),
        "failing": len(failing),
        "untested": len(untested),
        "satisfied": satisfied,
        "total_expectations": len(expectations),
        "all_satisfied": all_satisfied,
        "index_files": len(index.get("forward", {})),
    })


@mcp.tool()
def bdd_check(category: str = "") -> str:
    """Scan catalog and index for contradictions, orphans, and other issues.

    Args:
        category: Filter to one check type: overload, overlap, structural, status, coverage, semantic. Empty = all.
    """
    root = get_root()
    catalog = load_catalog(root)
    if not catalog:
        return "No catalog.json found"
    nodes = catalog["nodes"]
    index = load_index(root)
    forward = index.get("forward", {})
    reverse = index.get("reverse", {})
    test_results = index.get("test_results", {})

    node_map = {n["id"]: n for n in nodes}

    all_categories = ("overload", "overlap", "structural", "status", "coverage", "semantic")
    if category and category not in all_categories:
        return f"Unknown category '{category}'. Choose from: {', '.join(all_categories)}"
    cats = (category,) if category else all_categories

    sections = []
    total_issues = 0
    total_review = 0

    # --- Overload: multiple facets linked to the same test ---
    if "overload" in cats:
        test_to_facets = {}
        for n in nodes:
            if n["type"] == "facet" and n.get("test"):
                test_to_facets.setdefault(n["test"], []).append(n)
        issues = []
        for tid, facets in sorted(test_to_facets.items()):
            if len(facets) > 1:
                lines = [f'  [!] "{tid}" shared by {len(facets)} facets:']
                for f in facets:
                    parent = node_map.get(f.get("parent"), {})
                    pid = parent.get("id", "?")
                    lines.append(f"      {f['id']} ({pid}) {f['text']}")
                issues.append("\n".join(lines))
        if issues:
            sections.append(f"--- Test Overload ({len(issues)} issue{'s' if len(issues) != 1 else ''}) ---\n" + "\n\n".join(issues))
            total_issues += len(issues)

    # --- Overlap: facets from DIFFERENT expectations sharing source lines ---
    if "overlap" in cats:
        overlap_lines = {}  # (file, line) -> {exp_id: [facet_node]}
        for filepath, line_map in forward.items():
            for ls, fids in line_map.items():
                by_exp = {}
                for fid in fids:
                    fnode = node_map.get(fid)
                    if not fnode:
                        continue
                    exp_id = fnode.get("parent", "?")
                    by_exp.setdefault(exp_id, []).append(fnode)
                if len(by_exp) > 1:
                    overlap_lines[(filepath, int(ls))] = by_exp

        if overlap_lines:
            by_file = {}
            for (fp, ln), by_exp in overlap_lines.items():
                by_file.setdefault(fp, []).append((ln, by_exp))

            issues = []
            for fp in sorted(by_file):
                entries = sorted(by_file[fp], key=lambda x: x[0])
                # Merge contiguous lines into ranges
                ranges = []
                rng_start = entries[0][0]
                rng_end = entries[0][0]
                rng_facets = {}
                for ln, by_exp in entries:
                    if ln <= rng_end + 1:
                        rng_end = ln
                    else:
                        ranges.append((rng_start, rng_end, dict(rng_facets)))
                        rng_start = ln
                        rng_end = ln
                        rng_facets = {}
                    for eid, fnodes in by_exp.items():
                        rng_facets.setdefault(eid, set()).update(f["id"] for f in fnodes)
                ranges.append((rng_start, rng_end, dict(rng_facets)))

                for s, e, exp_facets in ranges:
                    rng_str = f"{s}-{e}" if s != e else str(s)
                    lines = [f"  [!] {fp}:{rng_str} claimed by different expectations:"]
                    for eid, fid_set in sorted(exp_facets.items()):
                        exp_node = node_map.get(eid, {})
                        exp_text = exp_node.get("text", "?")
                        for fid in sorted(fid_set):
                            fnode = node_map.get(fid, {})
                            lines.append(f"      {fid} ({eid}: {exp_text}) {fnode.get('text', '?')}")
                    issues.append("\n".join(lines))
            if issues:
                sections.append(f"--- Code Overlap ({len(issues)} issue{'s' if len(issues) != 1 else ''}) ---\n" + "\n\n".join(issues))
                total_issues += len(issues)

    # --- Structural: orphans, cycles, duplicates, empty expectations, type hierarchy ---
    if "structural" in cats:
        issues = []
        id_set = set(node_map.keys())

        # Orphan check
        for n in nodes:
            pid = n.get("parent")
            if pid and pid not in id_set:
                issues.append(f'  [!] Orphan: {n["id"]} parent "{pid}" does not exist')

        # Cycle detection
        for n in nodes:
            visited = set()
            cur = n
            while cur:
                if cur["id"] in visited:
                    issues.append(f'  [!] Cycle: {n["id"]} has circular parent chain')
                    break
                visited.add(cur["id"])
                pid = cur.get("parent")
                cur = node_map.get(pid) if pid else None

        # Duplicate text
        seen_texts = {}
        for n in nodes:
            key = (n["type"], n["text"].lower().strip())
            if key in seen_texts:
                issues.append(f'  [!] Duplicate: {n["id"]} and {seen_texts[key]} share text "{n["text"]}"')
            else:
                seen_texts[key] = n["id"]

        # Empty expectations
        for n in nodes:
            if n["type"] == "expectation":
                children = [c for c in nodes if c.get("parent") == n["id"]]
                if not children:
                    issues.append(f'  [!] Empty: {n["id"]} "{n["text"]}" has no facets')

        # Type hierarchy violations
        valid_parent_type = {"goal": (None,), "expectation": ("goal",), "facet": ("expectation",)}
        for n in nodes:
            pid = n.get("parent")
            if pid:
                parent_node = node_map.get(pid)
                if parent_node:
                    allowed = valid_parent_type.get(n["type"], ())
                    if parent_node["type"] not in allowed:
                        issues.append(f'  [!] Hierarchy: {n["id"]} ({n["type"]}) has parent {pid} ({parent_node["type"]})')
            elif n["type"] != "goal":
                issues.append(f'  [!] Hierarchy: {n["id"]} ({n["type"]}) has no parent (only goals can be root)')

        if issues:
            sections.append(f"--- Structural ({len(issues)} issue{'s' if len(issues) != 1 else ''}) ---\n" + "\n".join(issues))
            total_issues += len(issues)

    # --- Status: facet status disagrees with test results ---
    if "status" in cats:
        issues = []
        for n in nodes:
            if n["type"] != "facet" or not n.get("test"):
                continue
            matched_id, result = match_test_to_facet(test_results, n["test"])
            if matched_id is None:
                continue
            stored = n.get("status", "untested")
            if result == "passed" and stored != "passing":
                issues.append(f'  [!] {n["id"]} test passed but status is "{stored}"')
            elif result == "failed" and stored != "failing":
                issues.append(f'  [!] {n["id"]} test failed but status is "{stored}"')

        if issues:
            sections.append(f"--- Status Mismatch ({len(issues)} issue{'s' if len(issues) != 1 else ''}) ---\n" + "\n".join(issues))
            total_issues += len(issues)

    # --- Coverage: facet test passes but no lines in reverse index ---
    if "coverage" in cats:
        issues = []
        for n in nodes:
            if n["type"] != "facet" or not n.get("test"):
                continue
            matched_id, result = match_test_to_facet(test_results, n["test"])
            if result != "passed":
                continue
            if n["id"] not in reverse:
                issues.append(f'  [!] {n["id"]} "{n["text"]}" test passes but has no coverage lines')

        if issues:
            sections.append(f"--- Coverage Gap ({len(issues)} issue{'s' if len(issues) != 1 else ''}) ---\n" + "\n".join(issues))
            total_issues += len(issues)

    # --- Semantic: candidate contradictions between different expectations ---
    if "semantic" in cats:
        STOPWORDS = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                     "being", "have", "has", "had", "do", "does", "did", "will",
                     "would", "could", "should", "may", "might", "can", "shall",
                     "to", "of", "in", "for", "on", "with", "at", "by", "from",
                     "it", "its", "this", "that", "and", "or", "not", "no", "but",
                     "if", "then", "than", "so", "as", "up", "out", "about"}

        def keywords(text):
            words = set()
            for w in text.lower().split():
                w = w.strip(".,;:!?\"'()-")
                if len(w) > 1 and w not in STOPWORDS:
                    words.add(w)
            return words

        facets = [n for n in nodes if n["type"] == "facet"]
        pairs = []
        for i in range(len(facets)):
            for j in range(i + 1, len(facets)):
                a, b = facets[i], facets[j]
                if a.get("parent") == b.get("parent"):
                    continue

                shared_files = set()
                a_rev = reverse.get(a["id"], {})
                b_rev = reverse.get(b["id"], {})
                for fp in set(a_rev) & set(b_rev):
                    if set(a_rev[fp]) & set(b_rev[fp]):
                        shared_files.add(fp)

                kw_a = keywords(a["text"])
                kw_b = keywords(b["text"])
                shared_kw = kw_a & kw_b

                if shared_files or len(shared_kw) >= 2:
                    detail = []
                    if shared_files:
                        detail.append(f"Shared code: {', '.join(sorted(shared_files))}")
                    if shared_kw:
                        detail.append(f"Shared keywords: {', '.join(sorted(shared_kw))}")
                    pairs.append((a, b, detail))

        if pairs:
            issues = []
            for a, b, detail in pairs:
                lines = [
                    f'  [?] {a["id"]}: "{a["text"]}" ({a.get("parent", "?")})',
                    f'      {b["id"]}: "{b["text"]}" ({b.get("parent", "?")})',
                ]
                for d in detail:
                    lines.append(f"      {d}")
                issues.append("\n".join(lines))
            sections.append(f"--- Semantic Candidates ({len(pairs)} pair{'s' if len(pairs) != 1 else ''}) ---\n" + "\n\n".join(issues))
            total_review += len(pairs)

    # --- Build final report ---
    if not sections:
        return "=== Catalog Health Check ===\n\nNo issues found."

    parts = ["=== Catalog Health Check ===", ""]
    parts.extend(sections)
    parts.append("")
    summary_parts = []
    if total_issues:
        summary_parts.append(f"{total_issues} issue{'s' if total_issues != 1 else ''}")
    if total_review:
        summary_parts.append(f"{total_review} review candidate{'s' if total_review != 1 else ''}")
    parts.append(f"=== {', '.join(summary_parts)} ===")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI mode: --run-tests
# ---------------------------------------------------------------------------

def run_tests_cli(root):
    """Run tests, rebuild index, print summary, exit with status."""
    config = load_config(root)
    if not config:
        print("Error: No bdd.json found", file=sys.stderr)
        sys.exit(1)
    catalog = load_catalog(root)
    if not catalog:
        print("Error: No catalog.json found", file=sys.stderr)
        sys.exit(1)

    # Run test command
    test_cmd = config["test_command"]
    print(f"Running: {test_cmd}")
    subprocess.run(test_cmd, shell=True, cwd=root)

    # Build index
    build_result = build_index(root)
    if build_result is None:
        print("Error: Failed to build index", file=sys.stderr)
        sys.exit(1)

    index, updated = build_result

    # Print updates
    if updated:
        print()
        print("Facet updates:")
        for u in updated:
            print(f"  {u['id']}: {u['old']} -> {u['new']}")

    # Summary
    catalog = load_catalog(root)
    nodes = catalog["nodes"]
    facets = [n for n in nodes if n["type"] == "facet"]
    passing = [f for f in facets if f.get("status") == "passing"]
    failing = [f for f in facets if f.get("status") == "failing"]
    untested = [f for f in facets if f.get("status", "untested") == "untested"]
    expectations = [n for n in nodes if n["type"] == "expectation"]
    satisfied = sum(1 for e in expectations if compute_status(nodes, e) == "passing")
    all_satisfied = satisfied == len(expectations) and len(expectations) > 0

    print()
    print(f"Results: {len(index.get('test_results', {}))} tests parsed")
    print(f"Facets:  {len(passing)} passing, {len(failing)} failing, {len(untested)} untested")
    print(f"Expectations: {satisfied}/{len(expectations)} satisfied")
    if all_satisfied:
        print("All expectations satisfied!")

    sys.exit(0 if all_satisfied else 1)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def cli_query(args):
    """Run a tool from the command line: python3 bdd_server.py <root> <tool> [args...]"""
    global PROJECT_ROOT
    PROJECT_ROOT = os.path.abspath(args[0])

    tool = args[1]
    rest = args[2:]

    if tool == "status":
        print(bdd_status())
    elif tool == "next":
        print(bdd_next())
    elif tool == "tree":
        # tree [node_id] [--unsatisfied|--failing|--untested|--passing] [--depth N]
        node_id = ""
        status_filter = ""
        max_depth = 0
        i = 0
        while i < len(rest):
            if rest[i].startswith("--"):
                flag = rest[i].lstrip("-")
                if flag in ("unsatisfied", "failing", "untested", "passing"):
                    status_filter = flag
                elif flag == "depth" and i + 1 < len(rest):
                    i += 1
                    max_depth = int(rest[i])
            else:
                node_id = rest[i]
            i += 1
        print(bdd_tree(node_id=node_id, status_filter=status_filter, max_depth=max_depth))
    elif tool == "motivation":
        # motivation <file> [start_line] [end_line]
        file = rest[0] if rest else ""
        start = int(rest[1]) if len(rest) > 1 else 0
        end = int(rest[2]) if len(rest) > 2 else 0
        print(bdd_motivation(file, start, end))
    elif tool == "locate":
        # locate <node_id>
        print(bdd_locate(rest[0] if rest else ""))
    elif tool == "test":
        print(bdd_test())
    elif tool == "add":
        # add <type> <text> [--parent ID] [--priority N] [--labels a,b]
        node_type = rest[0] if rest else ""
        text = rest[1] if len(rest) > 1 else ""
        parent = ""
        priority = 1
        labels = ""
        i = 2
        while i < len(rest):
            if rest[i] == "--parent" and i + 1 < len(rest):
                i += 1; parent = rest[i]
            elif rest[i] == "--priority" and i + 1 < len(rest):
                i += 1; priority = int(rest[i])
            elif rest[i] == "--labels" and i + 1 < len(rest):
                i += 1; labels = rest[i]
            i += 1
        print(bdd_add(node_type, text, parent, priority, labels))
    elif tool == "link":
        # link <facet_id> <test_id>
        print(bdd_link(rest[0] if rest else "", rest[1] if len(rest) > 1 else ""))
    elif tool == "check":
        print(bdd_check(category=rest[0] if rest else ""))
    else:
        print(f"Unknown tool: {tool}")
        print("Available: status, next, tree, motivation, locate, test, add, link, check")
        sys.exit(1)


def main():
    if "--run-tests" in sys.argv:
        idx = sys.argv.index("--run-tests")
        root = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else os.getcwd()
        run_tests_cli(os.path.abspath(root))
    elif len(sys.argv) >= 3 and not sys.argv[2].startswith("-"):
        # CLI query mode: bdd_server.py <root> <tool> [args...]
        cli_query(sys.argv[1:])
    else:
        global PROJECT_ROOT
        if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
            PROJECT_ROOT = os.path.abspath(sys.argv[1])
        else:
            PROJECT_ROOT = os.getcwd()
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
