#!/usr/bin/env bash
# inject-context.sh — Surface BDD context after tool use.
# Called as a PostToolUse hook. Receives JSON on stdin with fields:
#   tool_name, tool_input, tool_response, session_id, cwd, etc.
#
# - After Read: injects motivation context for source files (line-level)
# - After Bash: shows unsatisfied expectations after test runs

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

PROJECT_ROOT=$(find_project_root 2>/dev/null) || exit 0

BDD_CMD=$(which bdd 2>/dev/null || echo "")
[ -n "$BDD_CMD" ] || exit 0

# Read hook input from stdin
HOOK_INPUT=$(cat)

TOOL_NAME=$(echo "$HOOK_INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_name', ''))
except:
    print('')
" 2>/dev/null)

if [ "$TOOL_NAME" = "Read" ]; then
    # --- Read hook: inject line-level motivation context ---
    eval "$(echo "$HOOK_INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    ti = data.get('tool_input', {})
    fp = ti.get('file_path', '')
    offset = ti.get('offset', '')
    limit = ti.get('limit', '')
    print(f'FILE_PATH=\"{fp}\"')
    print(f'READ_OFFSET=\"{offset}\"')
    print(f'READ_LIMIT=\"{limit}\"')
except:
    print('FILE_PATH=\"\"')
" 2>/dev/null)"

    [ -n "$FILE_PATH" ] || exit 0

    # Skip non-source files
    case "$FILE_PATH" in
        *test*|*/catalog.json|*/coverage_map.json|*.md|*.toml|*.yaml|*.yml|*.lock|*.json|*.cfg|*.ini)
            exit 0
            ;;
    esac

    # Build --lines args if offset/limit provided
    LINES_ARGS=""
    if [ -n "$READ_OFFSET" ] && [ -n "$READ_LIMIT" ]; then
        LINE_END=$((READ_OFFSET + READ_LIMIT))
        LINES_ARGS="--lines $READ_OFFSET $LINE_END"
    fi

    # Look up motivation chain
    RELATED=$($BDD_CMD --json related "$FILE_PATH" $LINES_ARGS 2>/dev/null || echo "")
    [ -n "$RELATED" ] || exit 0

    echo "$RELATED" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    related = data.get('related', [])
    if not related:
        sys.exit(0)
    lines = []
    for r in related:
        for c in r.get('chains', []):
            parts = ' > '.join(f\"{n['id']}: {n['text']}\" for n in c['chain'])
            lines.append(f'  {parts}')
    if lines:
        print()
        print('--- BDD: This code exists because ---')
        for l in lines:
            print(l)
        print('---')
except:
    pass
" 2>/dev/null

elif [ "$TOOL_NAME" = "Bash" ]; then
    # --- Bash hook: show status after test runs ---
    COMMAND=$(echo "$HOOK_INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_input', {}).get('command', ''))
except:
    print('')
" 2>/dev/null)

    if echo "$COMMAND" | grep -qiE 'pytest|cargo.test|cargo.llvm-cov|jest|vitest|go.test|npm.test|bdd.coverage'; then
        UNSATISFIED=$($BDD_CMD --json status 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['unsatisfied'])" 2>/dev/null || echo "")
        if [ -n "$UNSATISFIED" ] && [ "$UNSATISFIED" != "0" ]; then
            echo ""
            echo "--- BDD: $UNSATISFIED unsatisfied expectations remaining ---"
            $BDD_CMD next 2>/dev/null | head -10
            echo "---"
        fi
    fi
fi
