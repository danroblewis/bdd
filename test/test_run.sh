#!/bin/bash
# test_run.sh — E2E test of the BDD system.
# Creates a fresh project, seeds expectations, runs the implementation loop,
# and verifies expectations get satisfied.

set -e

BDD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BDD="$BDD_DIR/bdd"
TEST_DIR=$(mktemp -d)
PASS=0
FAIL=0

cleanup() {
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT

assert() {
    local desc="$1"
    local cmd="$2"
    local expected="$3"
    local actual
    actual=$(eval "$cmd" 2>&1) || true
    if [ "$actual" = "$expected" ]; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        echo "    Expected: $expected"
        echo "    Actual:   $actual"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local desc="$1"
    local cmd="$2"
    local expected="$3"
    local actual
    actual=$(eval "$cmd" 2>&1) || true
    if echo "$actual" | grep -q "$expected"; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        echo "    Expected to contain: $expected"
        echo "    Actual: $actual"
        FAIL=$((FAIL + 1))
    fi
}

assert_exit() {
    local desc="$1"
    local cmd="$2"
    local expected="$3"
    local code
    eval "$cmd" >/dev/null 2>&1 && code=0 || code=$?
    if [ "$code" = "$expected" ]; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        echo "    Expected exit code: $expected"
        echo "    Actual exit code:   $code"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== BDD System E2E Test ==="
echo "Test directory: $TEST_DIR"
echo ""

# --- Phase 1: Setup ---
echo "Phase 1: Project Setup"

cd "$TEST_DIR"
git init -q .

# Copy framework as .claude/
cp -r "$BDD_DIR/framework" .claude

# Make bdd available
export PATH="$BDD_DIR:$PATH"

# Initialize catalog
$BDD init
assert "catalog.json exists" "test -f catalog.json && echo yes" "yes"

echo ""

# --- Phase 2: Catalog CRUD ---
echo "Phase 2: Catalog CRUD Operations"

# Add goals
$BDD add goal "The calculator handles basic math" --priority 1 --label core
assert "goal added" "$BDD --json show g-001 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['text'])\"" "The calculator handles basic math"

# Add expectations
$BDD add expectation "Addition works correctly" --parent g-001 --priority 1
$BDD add expectation "Subtraction works correctly" --parent g-001 --priority 2
assert "two expectations" "$BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['expectations'])\"" "2"

# Add facets
$BDD add facet "2 + 3 equals 5" --parent e-001
$BDD add facet "0 + 0 equals 0" --parent e-001
$BDD add facet "5 - 3 equals 2" --parent e-002
assert "three facets" "$BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['facets'])\"" "3"

# Status checks
assert "all untested" "$BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['untested'])\"" "3"
assert "0% coverage" "$BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['coverage'])\"" "0.0"
assert "0 satisfied" "$BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['satisfied'])\"" "0"
assert "2 unsatisfied" "$BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['unsatisfied'])\"" "2"

# Mark facets
$BDD mark f-001 passing
$BDD mark f-002 passing
assert "e-001 satisfied" "$BDD --json show e-001 | python3 -c \"import sys,json; print(json.load(sys.stdin)['status'])\"" "passing"
assert "e-002 unsatisfied" "$BDD --json show e-002 | python3 -c \"import sys,json; print(json.load(sys.stdin)['status'])\"" "untested"
assert "1 satisfied" "$BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['satisfied'])\"" "1"

# Link tests
$BDD link f-001 tests/test_add.sh
assert "test linked" "$BDD --json show f-001 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['test'])\"" "tests/test_add.sh"

# Edit
$BDD edit f-001 "2 + 3 returns 5"
assert "text edited" "$BDD --json show f-001 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['text'])\"" "2 + 3 returns 5"

# Next returns highest priority unsatisfied
assert_contains "next returns e-002" "$BDD next" "e-002"

# Mark all passing
$BDD mark f-003 passing
assert "all satisfied" "$BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['unsatisfied'])\"" "0"
assert "100% coverage" "$BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['coverage'])\"" "100.0"

# Next when all satisfied
assert_contains "next says all satisfied" "$BDD next" "All expectations satisfied"

# Tree output
assert_contains "tree shows goal" "$BDD tree" "g-001"
assert_contains "tree shows passing" "$BDD tree" "[+]"

# Remove with children warning
assert_exit "remove warns about children" "$BDD remove e-001" "1"

# Remove with force
$BDD remove e-001 --force
assert "e-001 removed" "$BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['expectations'])\"" "1"

echo ""

# --- Phase 3: Framework Files ---
echo "Phase 3: Framework Verification"

assert "CLAUDE.md exists" "test -f .claude/CLAUDE.md && echo yes" "yes"
assert "settings.json exists" "test -f .claude/settings.json && echo yes" "yes"
assert "methodology.md exists" "test -f .claude/rules/methodology.md && echo yes" "yes"
assert "introspection.md exists" "test -f .claude/rules/introspection.md && echo yes" "yes"
assert "suggest skill exists" "test -f .claude/skills/suggest/SKILL.md && echo yes" "yes"
assert "curate skill exists" "test -f .claude/skills/curate/SKILL.md && echo yes" "yes"
assert "status skill exists" "test -f .claude/skills/status/SKILL.md && echo yes" "yes"
assert "bootstrap skill exists" "test -f .claude/skills/bootstrap/SKILL.md && echo yes" "yes"
assert "inject hook exists" "test -f .claude/hooks/inject-context.sh && echo yes" "yes"

# Check settings.json is valid JSON
assert_exit "settings.json is valid JSON" "python3 -c \"import json; json.load(open('.claude/settings.json'))\"" "0"

echo ""

# --- Phase 4: JSON output ---
echo "Phase 4: JSON Output Mode"

assert_exit "status --json valid" "$BDD --json status | python3 -c 'import sys,json; json.load(sys.stdin)'" "0"
assert_exit "tree --json valid" "$BDD --json tree | python3 -c 'import sys,json; json.load(sys.stdin)'" "0"

echo ""

# --- Summary ---
echo "================================"
TOTAL=$((PASS + FAIL))
echo "Results: $PASS/$TOTAL passed"
if [ "$FAIL" -gt 0 ]; then
    echo "FAILED ($FAIL failures)"
    exit 1
else
    echo "ALL PASSED"
    exit 0
fi
