#!/bin/bash
set -e
cp "$(dirname "$0")/test_208_mcp_health_check.py" "$WORKSPACE/tests/test_208_mcp_health_check.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_208_mcp_health_check.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/ --ignore=tests/test_208_mcp_health_check.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
