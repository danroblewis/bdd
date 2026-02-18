#!/usr/bin/env python3
"""Generate a self-contained HTML explorer for a BDD catalog.json file.

Usage:
    python3 catalog_explorer.py subject_2/catalog.json [--output catalog-explorer.html]
"""

import json
import re
import sys
from pathlib import Path


def load_catalog(path: Path) -> dict:
    with open(path) as f:
        catalog = json.load(f)
    if "nodes" not in catalog:
        print(f"Error: {path} does not contain a 'nodes' key", file=sys.stderr)
        sys.exit(1)
    return catalog


def compute_derived(catalog: dict) -> dict:
    nodes = catalog["nodes"]
    file_map = {}      # {source_file: [facet_ids]}
    test_map = {}      # {test_file: [facet_ids]}
    located_in = {}    # {facet_id: "backend/foo.py:Class.method"}

    loc_re = re.compile(r'Located in\s+(\S+?)\.?\s*$')

    for node in nodes:
        if node["type"] != "facet":
            continue
        fid = node["id"]
        text = node.get("text", "")
        m = loc_re.search(text)
        if m:
            ref = m.group(1)
            located_in[fid] = ref
            # Split on : to get file path
            parts = ref.split(":")
            src_file = parts[0] if parts else ref
            file_map.setdefault(src_file, []).append(fid)

        test = node.get("test", "")
        if test:
            # Extract test file from pytest-style test ID: tests/foo.py::Class::method
            test_file = test.split("::")[0] if "::" in test else test
            test_map.setdefault(test_file, []).append(fid)

    # Build node lookup helpers
    node_by_id = {n["id"]: n for n in nodes}

    def get_ancestors(nid):
        chain = []
        current = node_by_id.get(nid)
        while current:
            chain.append(current["id"])
            pid = current.get("parent")
            current = node_by_id.get(pid) if pid else None
        return chain

    # Roll up goal_files
    goal_files = {}
    goals = [n for n in nodes if n["type"] == "goal"]
    for goal in goals:
        gid = goal["id"]
        src_files = set()
        tst_files = set()
        # Collect all descendant facets
        for node in nodes:
            if node["type"] != "facet":
                continue
            ancestors = get_ancestors(node["id"])
            if gid in ancestors:
                fid = node["id"]
                if fid in located_in:
                    parts = located_in[fid].split(":")
                    src_files.add(parts[0])
                test = node.get("test", "")
                if test:
                    tst_files.add(test.split("::")[0] if "::" in test else test)
        goal_files[gid] = {
            "source_files": sorted(src_files),
            "test_files": sorted(tst_files),
        }

    return {
        "file_map": file_map,
        "test_map": test_map,
        "located_in": located_in,
        "goal_files": goal_files,
    }


JS_FILE_ORDER = [
    "data-init.js",
    "helpers.js",
    "state.js",
    "panel-hierarchy.js",
    "panel-files.js",
    "panel-stats.js",
    "panel-preview.js",
    "llm-simulations.js",
    "syntax-highlight.js",
    "init.js",
]


def generate_html(catalog: dict, derived: dict) -> str:
    data = {"catalog": catalog, "derived": derived}
    data_json = json.dumps(data, default=str)

    # Locate templates directory relative to this script
    script_dir = Path(__file__).resolve().parent
    tpl_dir = script_dir / "templates"

    # Read base HTML
    base_html = (tpl_dir / "base.html").read_text()

    # Concatenate CSS files in alphabetical order
    css_dir = tpl_dir / "css"
    css_parts = []
    for css_file in sorted(css_dir.glob("*.css")):
        css_parts.append(css_file.read_text())
    css_combined = "\n".join(css_parts)

    # Concatenate JS files in explicit order
    js_dir = tpl_dir / "js"
    js_parts = []
    for js_name in JS_FILE_ORDER:
        js_parts.append((js_dir / js_name).read_text())
    js_combined = "\n".join(js_parts)

    # Assemble
    html = base_html
    html = html.replace("/*CSS_PLACEHOLDER*/", css_combined)
    html = html.replace("/*JS_PLACEHOLDER*/", js_combined)
    html = html.replace("/*DATA_PLACEHOLDER*/", data_json)
    return html


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python3 catalog_explorer.py <catalog.json> [--output <file.html>]")
        sys.exit(0)

    catalog_path = Path(sys.argv[1])
    output_path = Path("catalog-explorer.html")

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--output" and i + 1 < len(sys.argv):
            output_path = Path(sys.argv[i + 1])
            i += 2
        else:
            print(f"Unknown argument: {sys.argv[i]}", file=sys.stderr)
            sys.exit(1)

    catalog = load_catalog(catalog_path)
    derived = compute_derived(catalog)
    html = generate_html(catalog, derived)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Catalog explorer written to: {output_path}")


if __name__ == "__main__":
    main()
