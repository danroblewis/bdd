#!/usr/bin/env bash
# inject-context.sh — Surface BDD motivation context after Read tool use.
# Reads .bdd/index.json directly (no CLI dependency).
# Called as a PostToolUse hook for Read. Receives JSON on stdin.

LOGFILE="${CLAUDE_PROJECT_DIR:-.}/.bdd/hook.log"

log() {
    local ts
    ts=$(date '+%H:%M:%S')
    echo "[$ts] $*" >> "$LOGFILE" 2>/dev/null
}

# Find the project root (where catalog.json lives)
find_project_root() {
    local dir="$PWD"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/catalog.json" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

PROJECT_ROOT=$(find_project_root 2>/dev/null)
if [ -z "$PROJECT_ROOT" ]; then
    log "no project root found (no catalog.json)"
    exit 0
fi

INDEX_FILE="$PROJECT_ROOT/.bdd/index.json"
CATALOG_FILE="$PROJECT_ROOT/catalog.json"

if [ ! -f "$INDEX_FILE" ]; then
    log "no index file: $INDEX_FILE"
    exit 0
fi
if [ ! -f "$CATALOG_FILE" ]; then
    log "no catalog file: $CATALOG_FILE"
    exit 0
fi

# Read hook input from stdin
HOOK_INPUT=$(cat)
log "hook fired, input length: ${#HOOK_INPUT}"

# Pass hook input via stdin to python, not shell interpolation
echo "$HOOK_INPUT" | python3 -c "
import sys, json, os

hook = json.load(sys.stdin)
tool_name = hook.get('tool_name', '')
if tool_name != 'Read':
    sys.exit(0)

ti = hook.get('tool_input', {})
file_path = ti.get('file_path', '')
if not file_path:
    sys.exit(0)

# Log helper — append to logfile
logfile = '$LOGFILE'
def log(msg):
    if logfile:
        try:
            with open(logfile, 'a') as f:
                f.write(f'  py: {msg}\n')
        except:
            pass

log(f'Read: {file_path}')

# Skip non-source files
skip_patterns = ('test', 'catalog.json', 'index.json', '.md', '.toml', '.yaml',
                 '.yml', '.lock', '.json', '.cfg', '.ini', '.bdd/')
for pat in skip_patterns:
    if pat in file_path:
        log(f'skipped (pattern: {pat})')
        sys.exit(0)

project_root = '$PROJECT_ROOT'
index_file = '$INDEX_FILE'
catalog_file = '$CATALOG_FILE'

# Load index
try:
    with open(index_file) as f:
        index = json.load(f)
    with open(catalog_file) as f:
        catalog = json.load(f)
except Exception as e:
    log(f'load error: {e}')
    sys.exit(0)

forward = index.get('forward', {})
nodes = catalog.get('nodes', [])
log(f'index has {len(forward)} files, catalog has {len(nodes)} nodes')

# Find matching file in forward map
rel_path = os.path.relpath(file_path, project_root) if os.path.isabs(file_path) else file_path
matched = {f: lines for f, lines in forward.items() if rel_path in f or f in rel_path}
if not matched:
    log(f'no match for {rel_path}')
    sys.exit(0)

log(f'matched {len(matched)} files for {rel_path}')

# Get line range
offset = ti.get('offset', 0) or 0
limit = ti.get('limit', 0) or 0
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
    log(f'no facets for matched lines')
    sys.exit(0)

log(f'found {len(facet_ids)} facets: {sorted(facet_ids)}')

# Build deduplicated tree from facet chains
node_map = {n['id']: n for n in nodes}
tree_nodes = {}  # nid -> {node, children set}
tree_roots = set()
for fid in sorted(facet_ids):
    chain = []
    current = node_map.get(fid)
    while current:
        chain.append(current)
        pid = current.get('parent')
        current = node_map.get(pid) if pid else None
    chain.reverse()
    for i, n in enumerate(chain):
        if n['id'] not in tree_nodes:
            tree_nodes[n['id']] = {'node': n, 'children': set()}
        if i > 0:
            tree_nodes[chain[i-1]['id']]['children'].add(n['id'])
        else:
            tree_roots.add(n['id'])

if tree_nodes:
    log(f'injecting motivation tree ({len(facet_ids)} facets)')
    print()
    print('--- BDD: This code exists because ---')
    def render(nid, indent=0):
        tn = tree_nodes[nid]
        n = tn['node']
        prefix = '  ' * indent
        t = n['type'][0].upper()
        print(f'  {prefix}{n[\"id\"]} [{t}] {n[\"text\"]}')
        for cid in sorted(tn['children']):
            render(cid, indent + 1)
    for rid in sorted(tree_roots):
        render(rid)
    print('---')
else:
    log('no chains built')
" 2>>"$LOGFILE"
