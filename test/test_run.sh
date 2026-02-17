#!/bin/bash
# test_run.sh — E2E test of the BDD system.
# Tests the MCP server's core logic by importing as a Python module,
# the bdd CLI, setup command, and index building.

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
$BDD link f-001 "tests/test_behavior.py::test_add"
assert "test linked" "$BDD --json show f-001 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['test'])\"" "tests/test_behavior.py::test_add"

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
assert "bdd skill exists" "test -f .claude/skills/bdd/SKILL.md && echo yes" "yes"
assert "inject hook exists" "test -f .claude/hooks/inject-context.sh && echo yes" "yes"

# Check settings.json is valid JSON
assert_exit "settings.json is valid JSON" "python3 -c \"import json; json.load(open('.claude/settings.json'))\"" "0"

echo ""

# --- Phase 4: JSON output ---
echo "Phase 4: JSON Output Mode"

assert_exit "status --json valid" "$BDD --json status | python3 -c 'import sys,json; json.load(sys.stdin)'" "0"
assert_exit "tree --json valid" "$BDD --json tree | python3 -c 'import sys,json; json.load(sys.stdin)'" "0"

echo ""

# --- Phase 5: MCP Server Core Logic ---
echo "Phase 5: MCP Server Core Logic"

# Test server functions by importing as Python module
MCP_TEST_DIR=$(mktemp -d)
cd "$MCP_TEST_DIR"
git init -q .

python3 -c "
import sys, json, os
sys.path.insert(0, '$BDD_DIR')
from bdd_server import *

root = '$MCP_TEST_DIR'

# Test catalog operations
save_catalog({'version': 1, 'nodes': []}, root)
cat = load_catalog(root)
assert cat is not None, 'catalog loaded'
assert cat['version'] == 1, 'version correct'

# Test node operations
nodes = cat['nodes']
nid = next_id(nodes, 'g')
assert nid == 'g-001', f'next_id wrong: {nid}'

# Add nodes manually
nodes.append({'id': 'g-001', 'type': 'goal', 'text': 'Test goal', 'parent': None, 'priority': 1, 'labels': []})
nodes.append({'id': 'e-001', 'type': 'expectation', 'text': 'Test expectation', 'parent': 'g-001', 'priority': 1, 'labels': []})
nodes.append({'id': 'f-001', 'type': 'facet', 'text': 'Test facet 1', 'parent': 'e-001', 'test': 'tests/test_calc.py::test_add', 'status': 'untested'})
nodes.append({'id': 'f-002', 'type': 'facet', 'text': 'Test facet 2', 'parent': 'e-001', 'test': 'tests/test_calc.py::test_sub', 'status': 'untested'})
save_catalog(cat, root)

# Test get_node, get_children, compute_status
assert get_node(nodes, 'g-001') is not None
assert len(get_children(nodes, 'e-001')) == 2
assert compute_status(nodes, get_node(nodes, 'e-001')) == 'untested'

# Test ancestor chain
chain = get_ancestor_chain(nodes, 'f-001')
assert len(chain) == 3, f'chain length: {len(chain)}'
assert chain[0]['id'] == 'g-001'
assert chain[2]['id'] == 'f-001'

# Test status computation
nodes[2]['status'] = 'passing'
nodes[3]['status'] = 'passing'
save_catalog(cat, root)
assert compute_status(nodes, get_node(nodes, 'e-001')) == 'passing'

# Test index operations
idx = load_index(root)
assert idx == {'forward': {}, 'reverse': {}, 'test_results': {}, 'facet_status': {}}
save_index(idx, root)
assert os.path.exists(os.path.join(root, '.bdd', 'index.json'))

print('All server core logic tests passed')
"

assert_exit "server core logic" "python3 -c \"
import sys; sys.path.insert(0, '$BDD_DIR')
from bdd_server import *
root = '$MCP_TEST_DIR'
cat = load_catalog(root)
assert cat is not None
\"" "0"

echo ""

# --- Phase 6: Index Building ---
echo "Phase 6: Index Building"

cd "$MCP_TEST_DIR"

# Reset catalog
python3 -c "
import sys, json, os
sys.path.insert(0, '$BDD_DIR')
from bdd_server import *

root = '$MCP_TEST_DIR'
cat = {'version': 1, 'nodes': [
    {'id': 'g-001', 'type': 'goal', 'text': 'Calculator works', 'parent': None, 'priority': 1, 'labels': []},
    {'id': 'e-001', 'type': 'expectation', 'text': 'Addition works', 'parent': 'g-001', 'priority': 1, 'labels': []},
    {'id': 'f-001', 'type': 'facet', 'text': '2+3=5', 'parent': 'e-001', 'test': 'tests/test_calc.py::test_add', 'status': 'untested'},
    {'id': 'f-002', 'type': 'facet', 'text': '0+0=0', 'parent': 'e-001', 'test': 'tests/test_calc.py::test_add_zeros', 'status': 'untested'},
    {'id': 'e-002', 'type': 'expectation', 'text': 'Display works', 'parent': 'g-001', 'priority': 2, 'labels': []},
    {'id': 'f-003', 'type': 'facet', 'text': 'display shows result', 'parent': 'e-002', 'test': None, 'status': 'untested'},
]}
save_catalog(cat, root)
"

# Create bdd.json
cat > "$MCP_TEST_DIR/bdd.json" << 'BDDEOF'
{
  "test_command": "true",
  "results_format": "junit",
  "results_file": "results.xml",
  "coverage_format": "coverage-json",
  "coverage_file": "coverage.json"
}
BDDEOF

# Create JUnit XML results
cat > "$MCP_TEST_DIR/results.xml" << 'JUNITEOF'
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="tests" tests="2" errors="0" failures="0">
    <testcase classname="tests/test_calc.py" name="test_add" time="0.01"/>
    <testcase classname="tests/test_calc.py" name="test_add_zeros" time="0.01"/>
  </testsuite>
</testsuites>
JUNITEOF

# Create coverage.json with per-test contexts
cat > "$MCP_TEST_DIR/coverage.json" << 'COVEOF'
{
  "files": {
    "src/calc.py": {
      "contexts": {
        "tests/test_calc.py::test_add": [1, 2, 3, 10, 11],
        "tests/test_calc.py::test_add_zeros": [1, 2, 4]
      }
    },
    "src/display.py": {
      "contexts": {
        "tests/test_calc.py::test_add": [5, 6, 7]
      }
    }
  }
}
COVEOF

# Build index and verify
python3 -c "
import sys, json, os
sys.path.insert(0, '$BDD_DIR')
from bdd_server import *

root = '$MCP_TEST_DIR'
result = build_index(root)
assert result is not None, 'build_index returned None'
index, updated = result

# Verify test results parsed
assert len(index['test_results']) == 2, f'Expected 2 test results, got {len(index[\"test_results\"])}'
assert index['test_results']['tests/test_calc.py::test_add'] == 'passed'
assert index['test_results']['tests/test_calc.py::test_add_zeros'] == 'passed'

# Verify facet statuses updated
cat = load_catalog(root)
nodes = cat['nodes']
f001 = get_node(nodes, 'f-001')
f002 = get_node(nodes, 'f-002')
f003 = get_node(nodes, 'f-003')
assert f001['status'] == 'passing', f'f-001 status: {f001[\"status\"]}'
assert f002['status'] == 'passing', f'f-002 status: {f002[\"status\"]}'
assert f003['status'] == 'untested', f'f-003 status: {f003[\"status\"]}'

# Verify forward map
fwd = index['forward']
assert 'src/calc.py' in fwd, f'src/calc.py not in forward: {list(fwd.keys())}'
assert '10' in fwd['src/calc.py'], f'line 10 not in forward map'
assert fwd['src/calc.py']['10'] == ['f-001'], f'line 10 maps to: {fwd[\"src/calc.py\"][\"10\"]}'
assert '4' in fwd['src/calc.py'], f'line 4 not in forward map'
assert fwd['src/calc.py']['4'] == ['f-002'], f'line 4 maps to: {fwd[\"src/calc.py\"][\"4\"]}'
# Shared lines
assert '1' in fwd['src/calc.py']
assert sorted(fwd['src/calc.py']['1']) == ['f-001', 'f-002'], f'shared line 1: {fwd[\"src/calc.py\"][\"1\"]}'

# Verify reverse map
rev = index['reverse']
assert 'f-001' in rev
assert 'src/calc.py' in rev['f-001']
assert 10 in rev['f-001']['src/calc.py']
assert 'src/display.py' in rev['f-001']
assert 5 in rev['f-001']['src/display.py']

# Verify index file was saved
assert os.path.exists(os.path.join(root, '.bdd', 'index.json'))

print('All index building tests passed')
"

assert_exit "index building" "python3 -c \"
import sys; sys.path.insert(0, '$BDD_DIR')
from bdd_server import *
root = '$MCP_TEST_DIR'
result = build_index(root)
assert result is not None
\"" "0"

# Test bdd_motivation tree output
python3 -c "
import sys, os
sys.path.insert(0, '$BDD_DIR')
import bdd_server
bdd_server.PROJECT_ROOT = '$MCP_TEST_DIR'

result = bdd_server.bdd_motivation('src/calc.py')
print('Motivation output:')
print(result)

# Should be tree format, not flat chains
assert '--- This code exists because ---' in result, 'missing header'
assert '---' in result, 'missing footer'

# g-001 should appear exactly once (deduplicated)
count = result.count('g-001')
assert count == 1, f'g-001 appears {count} times (should be 1 — deduplicated)'

# Both facets should appear
assert 'f-001' in result, 'missing f-001'
assert 'f-002' in result, 'missing f-002'

# e-001 should appear once (shared parent)
e_count = result.count('e-001')
assert e_count == 1, f'e-001 appears {e_count} times (should be 1)'

# Type labels should be present
assert '[G]' in result, 'missing [G] type label'
assert '[E]' in result, 'missing [E] type label'
assert '[F]' in result, 'missing [F] type label'

# Indentation: facets should be indented more than their parent
lines = result.split('\n')
for line in lines:
    if 'f-001' in line:
        f_indent = len(line) - len(line.lstrip())
    if 'e-001' in line:
        e_indent = len(line) - len(line.lstrip())
    if 'g-001' in line:
        g_indent = len(line) - len(line.lstrip())
assert f_indent > e_indent, f'facet indent ({f_indent}) not > expectation indent ({e_indent})'
assert e_indent > g_indent, f'expectation indent ({e_indent}) not > goal indent ({g_indent})'

print('All motivation tree tests passed')
"

assert_exit "motivation tree output" "python3 -c \"
import sys; sys.path.insert(0, '$BDD_DIR')
import bdd_server
bdd_server.PROJECT_ROOT = '$MCP_TEST_DIR'
result = bdd_server.bdd_motivation('src/calc.py')
assert '--- This code exists because ---' in result
\"" "0"

echo ""

# --- Phase 7: Setup Command ---
echo "Phase 7: Setup Command"

SETUP_DIR=$(mktemp -d)

# Setup on fresh directory
$BDD setup "$SETUP_DIR" >/dev/null 2>&1
assert "setup creates .claude" "test -d $SETUP_DIR/.claude && echo yes" "yes"
assert "setup creates catalog" "test -f $SETUP_DIR/catalog.json && echo yes" "yes"
assert "setup creates setup.md" "test -f $SETUP_DIR/.claude/rules/setup.md && echo yes" "yes"
assert "setup creates .mcp.json" "test -f $SETUP_DIR/.mcp.json && echo yes" "yes"
assert "setup creates .bdd dir" "test -d $SETUP_DIR/.bdd && echo yes" "yes"

# Verify .mcp.json points to bdd_server.py
assert_contains ".mcp.json has bdd_server" "cat $SETUP_DIR/.mcp.json" "bdd_server.py"
assert_contains ".mcp.json has bdd-catalog" "cat $SETUP_DIR/.mcp.json" "bdd-catalog"

# Verify .gitignore has .bdd/
assert_contains ".gitignore has .bdd/" "cat $SETUP_DIR/.gitignore" ".bdd/"

# Setup goal has priority 0
assert "setup goal priority 0" "cd $SETUP_DIR && $BDD --json show g-001 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['priority'])\"" "0"

# bdd next returns setup expectation first
assert_contains "next returns setup expectation" "cd $SETUP_DIR && $BDD next" "coverage tooling"

# Setup on existing catalog preserves existing nodes
SETUP_DIR2=$(mktemp -d)
cd "$SETUP_DIR2"
$BDD init >/dev/null
$BDD add goal "My existing goal" >/dev/null
$BDD setup "$SETUP_DIR2" >/dev/null 2>&1
assert "existing goal preserved" "cd $SETUP_DIR2 && $BDD --json show g-001 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['text'])\"" "My existing goal"
assert "setup goal added as g-002" "cd $SETUP_DIR2 && $BDD --json show g-002 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['text'])\"" "The project is set up for BDD development"

# Re-running setup doesn't duplicate setup nodes
$BDD setup "$SETUP_DIR2" --force >/dev/null 2>&1
assert "no duplicate setup goals" "cd $SETUP_DIR2 && $BDD --json status | python3 -c \"import sys,json; print(json.load(sys.stdin)['goals'])\"" "2"

rm -rf "$SETUP_DIR" "$SETUP_DIR2"
cd "$TEST_DIR"

echo ""

# --- Phase 8: bdd test (CLI) ---
echo "Phase 8: bdd test Command"

BDD_TEST_DIR=$(mktemp -d)
cd "$BDD_TEST_DIR"
git init -q .

# Initialize catalog and add nodes
$BDD init >/dev/null
$BDD add goal "Calculator works" --priority 1 >/dev/null
$BDD add expectation "Addition works" --parent g-001 --priority 1 >/dev/null
$BDD add expectation "Display works" --parent g-001 --priority 2 >/dev/null
$BDD add facet "2+3=5" --parent e-001 >/dev/null
$BDD add facet "0+0=0" --parent e-001 >/dev/null
$BDD add facet "display shows result" --parent e-002 >/dev/null

# Link test identifiers
$BDD link f-001 "tests/test_calc.py::test_add"
$BDD link f-002 "tests/test_calc.py::test_add_zeros"
# f-003 intentionally unlinked

# Create bdd.json (JUnit format)
cat > "$BDD_TEST_DIR/bdd.json" << 'BDDEOF'
{
  "test_command": "true",
  "results_format": "junit",
  "results_file": "results.xml",
  "coverage_format": "coverage-json",
  "coverage_file": "coverage.json"
}
BDDEOF

# Create passing JUnit XML results
cat > "$BDD_TEST_DIR/results.xml" << 'JUNITEOF'
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="tests" tests="2" errors="0" failures="0">
    <testcase classname="tests/test_calc.py" name="test_add" time="0.01"/>
    <testcase classname="tests/test_calc.py" name="test_add_zeros" time="0.01"/>
  </testsuite>
</testsuites>
JUNITEOF

# Create coverage.json
cat > "$BDD_TEST_DIR/coverage.json" << 'COVEOF'
{
  "files": {
    "src/calc.py": {
      "contexts": {
        "tests/test_calc.py::test_add": [1, 2, 3],
        "tests/test_calc.py::test_add_zeros": [1, 2, 4]
      }
    }
  }
}
COVEOF

# Run bdd test — should mark f-001 and f-002 passing
$BDD test >/dev/null 2>&1 || true
assert "f-001 marked passing" "cd $BDD_TEST_DIR && $BDD --json show f-001 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['status'])\"" "passing"
assert "f-002 marked passing" "cd $BDD_TEST_DIR && $BDD --json show f-002 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['status'])\"" "passing"
assert "f-003 stays untested" "cd $BDD_TEST_DIR && $BDD --json show f-003 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['status'])\"" "untested"
assert "coverage_map.json created" "test -f $BDD_TEST_DIR/coverage_map.json && echo yes" "yes"

# bdd test exits 1 because not all expectations are satisfied (f-003 untested)
assert_exit "bdd test exits 1 (not all satisfied)" "cd $BDD_TEST_DIR && $BDD test" "1"

# Swap in a failing result for f-001
cat > "$BDD_TEST_DIR/results.xml" << 'JUNITEOF'
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="tests" tests="2" errors="0" failures="1">
    <testcase classname="tests/test_calc.py" name="test_add" time="0.01">
      <failure message="assert 2+3==6">AssertionError</failure>
    </testcase>
    <testcase classname="tests/test_calc.py" name="test_add_zeros" time="0.01"/>
  </testsuite>
</testsuites>
JUNITEOF

$BDD test >/dev/null 2>&1 || true
assert "f-001 marked failing" "cd $BDD_TEST_DIR && $BDD --json show f-001 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['status'])\"" "failing"
assert "f-002 still passing" "cd $BDD_TEST_DIR && $BDD --json show f-002 | python3 -c \"import sys,json; print(json.load(sys.stdin)['node']['status'])\"" "passing"

# Test --json output
JOUT=$(cd $BDD_TEST_DIR && $BDD --json test 2>/dev/null || true)
assert "json output has results_parsed" "echo '$JOUT' | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d['results_parsed'])\"" "2"
assert "json output has all_satisfied" "echo '$JOUT' | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d['all_satisfied'])\"" "False"

# Test all expectations satisfied -> exit 0
cd "$BDD_TEST_DIR"
cat > "$BDD_TEST_DIR/results.xml" << 'JUNITEOF'
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="tests" tests="3" errors="0" failures="0">
    <testcase classname="tests/test_calc.py" name="test_add" time="0.01"/>
    <testcase classname="tests/test_calc.py" name="test_add_zeros" time="0.01"/>
    <testcase classname="tests/test_display.py" name="test_display" time="0.01"/>
  </testsuite>
</testsuites>
JUNITEOF

$BDD link f-003 "tests/test_display.py::test_display"
assert_exit "bdd test exits 0 (all satisfied)" "cd $BDD_TEST_DIR && $BDD test" "0"

rm -rf "$BDD_TEST_DIR"
cd "$TEST_DIR"

echo ""

# --- Phase 9: --run-tests mode ---
echo "Phase 9: --run-tests Mode"

RT_DIR=$(mktemp -d)
cd "$RT_DIR"
git init -q .

# Set up a simple project
python3 -c "
import sys, json, os
sys.path.insert(0, '$BDD_DIR')
from bdd_server import save_catalog

save_catalog({'version': 1, 'nodes': [
    {'id': 'g-001', 'type': 'goal', 'text': 'Works', 'parent': None, 'priority': 1, 'labels': []},
    {'id': 'e-001', 'type': 'expectation', 'text': 'Does thing', 'parent': 'g-001', 'priority': 1, 'labels': []},
    {'id': 'f-001', 'type': 'facet', 'text': 'thing works', 'parent': 'e-001', 'test': 'tests/test.py::test_thing', 'status': 'untested'},
]}, '$RT_DIR')
"

cat > "$RT_DIR/bdd.json" << 'EOF'
{
  "test_command": "true",
  "results_format": "junit",
  "results_file": "results.xml",
  "coverage_format": "coverage-json",
  "coverage_file": "coverage.json"
}
EOF

cat > "$RT_DIR/results.xml" << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="tests" tests="1">
    <testcase classname="tests/test.py" name="test_thing" time="0.01"/>
  </testsuite>
</testsuites>
EOF

cat > "$RT_DIR/coverage.json" << 'EOF'
{
  "files": {
    "src/main.py": {
      "contexts": {
        "tests/test.py::test_thing": [1, 2, 3]
      }
    }
  }
}
EOF

# --run-tests should exit 0 (all satisfied)
assert_exit "run-tests exits 0" "python3 $BDD_DIR/bdd_server.py --run-tests $RT_DIR" "0"

# Verify index was built
assert ".bdd/index.json created" "test -f $RT_DIR/.bdd/index.json && echo yes" "yes"

# Verify facet was updated
assert "facet updated to passing" "python3 -c \"
import sys, json; sys.path.insert(0, '$BDD_DIR')
from bdd_server import load_catalog, get_node
cat = load_catalog('$RT_DIR')
print(get_node(cat['nodes'], 'f-001')['status'])
\"" "passing"

rm -rf "$RT_DIR"
cd "$TEST_DIR"

echo ""

# --- Phase 10: bdd_check ---
echo "Phase 10: bdd_check Health Checks"

CHK_DIR=$(mktemp -d)
cd "$CHK_DIR"
git init -q .

# Create a catalog with known issues
python3 -c "
import sys, json, os
sys.path.insert(0, '$BDD_DIR')
from bdd_server import save_catalog, save_index

# Catalog with issues:
# - f-001 and f-002 share the same test (overload)
# - f-099 has orphan parent e-050
# - f-003 has status 'untested' but test passed (status mismatch)
# - e-003 has no children (empty)
# - f-004 is a facet parented to a facet (hierarchy violation)
cat = {'version': 1, 'nodes': [
    {'id': 'g-001', 'type': 'goal', 'text': 'Calculator works', 'parent': None, 'priority': 1, 'labels': []},
    {'id': 'e-001', 'type': 'expectation', 'text': 'Addition works', 'parent': 'g-001', 'priority': 1, 'labels': []},
    {'id': 'e-002', 'type': 'expectation', 'text': 'Division edge cases', 'parent': 'g-001', 'priority': 2, 'labels': []},
    {'id': 'e-003', 'type': 'expectation', 'text': 'Empty expectation', 'parent': 'g-001', 'priority': 3, 'labels': []},
    {'id': 'f-001', 'type': 'facet', 'text': '2+3=5', 'parent': 'e-001', 'test': 'tests/test.py::test_add', 'status': 'passing'},
    {'id': 'f-002', 'type': 'facet', 'text': 'addition commutes', 'parent': 'e-001', 'test': 'tests/test.py::test_add', 'status': 'passing'},
    {'id': 'f-003', 'type': 'facet', 'text': 'div by zero', 'parent': 'e-002', 'test': 'tests/test.py::test_div', 'status': 'untested'},
    {'id': 'f-099', 'type': 'facet', 'text': 'orphan facet', 'parent': 'e-050', 'test': None, 'status': 'untested'},
    {'id': 'f-004', 'type': 'facet', 'text': 'bad parent', 'parent': 'f-001', 'test': None, 'status': 'untested'},
]}
save_catalog(cat, '$CHK_DIR')

# Create index with test results showing f-003's test passed (but status is untested)
# Also f-005 passes but has no coverage lines
index = {
    'forward': {
        'src/calc.py': {
            '10': ['f-001', 'f-003'],
            '11': ['f-001'],
            '12': ['f-003']
        }
    },
    'reverse': {
        'f-001': {'src/calc.py': [10, 11]},
        'f-003': {'src/calc.py': [10, 12]}
    },
    'test_results': {
        'tests/test.py::test_add': 'passed',
        'tests/test.py::test_div': 'passed'
    },
    'facet_status': {}
}
save_index(index, '$CHK_DIR')
"

# Test check (all categories)
CHECK_OUT=$(python3 "$BDD_DIR/bdd_server.py" "$CHK_DIR" check 2>&1)
assert_contains "check detects overload" "echo '$CHECK_OUT'" "Test Overload"
assert_contains "check detects shared test" "echo '$CHECK_OUT'" "test_add"
assert_contains "check detects orphan" "echo '$CHECK_OUT'" "Orphan"
assert_contains "check detects orphan parent" "echo '$CHECK_OUT'" "e-050"
assert_contains "check detects status mismatch" "echo '$CHECK_OUT'" "Status Mismatch"
assert_contains "check detects empty expectation" "echo '$CHECK_OUT'" "Empty"
assert_contains "check detects hierarchy violation" "echo '$CHECK_OUT'" "Hierarchy"
assert_contains "check detects overlap" "echo '$CHECK_OUT'" "Code Overlap"

# Test filtered check
OVERLOAD_OUT=$(python3 "$BDD_DIR/bdd_server.py" "$CHK_DIR" check overload 2>&1)
assert_contains "filtered overload has Overload" "echo '$OVERLOAD_OUT'" "Test Overload"

STRUCT_OUT=$(python3 "$BDD_DIR/bdd_server.py" "$CHK_DIR" check structural 2>&1)
assert_contains "filtered structural has Orphan" "echo '$STRUCT_OUT'" "Orphan"

# Test clean catalog has no issues
CLEAN_DIR=$(mktemp -d)
cd "$CLEAN_DIR"
git init -q .
python3 -c "
import sys, json, os
sys.path.insert(0, '$BDD_DIR')
from bdd_server import save_catalog, save_index

cat = {'version': 1, 'nodes': [
    {'id': 'g-001', 'type': 'goal', 'text': 'Works', 'parent': None, 'priority': 1, 'labels': []},
    {'id': 'e-001', 'type': 'expectation', 'text': 'Does thing', 'parent': 'g-001', 'priority': 1, 'labels': []},
    {'id': 'f-001', 'type': 'facet', 'text': 'thing works', 'parent': 'e-001', 'test': 'tests/test.py::test_thing', 'status': 'passing'},
]}
save_catalog(cat, '$CLEAN_DIR')

index = {
    'forward': {'src/main.py': {'1': ['f-001']}},
    'reverse': {'f-001': {'src/main.py': [1]}},
    'test_results': {'tests/test.py::test_thing': 'passed'},
    'facet_status': {}
}
save_index(index, '$CLEAN_DIR')
"

CLEAN_OUT=$(python3 "$BDD_DIR/bdd_server.py" "$CLEAN_DIR" check 2>&1)
assert_contains "clean catalog has no issues" "echo '$CLEAN_OUT'" "No issues found"

# Test invalid category
INVALID_OUT=$(python3 "$BDD_DIR/bdd_server.py" "$CLEAN_DIR" check bogus 2>&1)
assert_contains "invalid category error" "echo '$INVALID_OUT'" "Unknown category"

rm -rf "$CHK_DIR" "$CLEAN_DIR"
cd "$TEST_DIR"

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
