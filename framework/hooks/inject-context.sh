#!/usr/bin/env bash
# inject-context.sh — Surface BDD context after tool use.
# Called as a PostToolUse hook for Bash commands.
# Shows unsatisfied expectations after test runs and motivation chains after file reads.

# Find the project root (where catalog.json lives)
find_catalog() {
    local dir="$PWD"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/catalog.json" ]; then
            echo "$dir/catalog.json"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

CATALOG=$(find_catalog 2>/dev/null) || exit 0

# Check if this was a test-related command
if echo "$TOOL_INPUT" 2>/dev/null | grep -qE 'test|run_all|run_e2e|pytest|cargo test|npm test'; then
    # Show BDD status after test runs
    BDD_CMD=$(which bdd 2>/dev/null || echo "")
    if [ -n "$BDD_CMD" ]; then
        UNSATISFIED=$($BDD_CMD --json status 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['unsatisfied'])" 2>/dev/null || echo "")
        if [ -n "$UNSATISFIED" ] && [ "$UNSATISFIED" != "0" ]; then
            echo ""
            echo "--- BDD: $UNSATISFIED unsatisfied expectations remaining ---"
            $BDD_CMD next 2>/dev/null | head -10
            echo "---"
        fi
    fi
fi
