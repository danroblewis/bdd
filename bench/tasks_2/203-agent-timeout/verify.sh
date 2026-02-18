#!/bin/bash
set -e
cp "$(dirname "$0")/test_203_agent_timeout.py" "$WORKSPACE/tests/test_203_agent_timeout.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_203_agent_timeout.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/ --ignore=tests/test_203_agent_timeout.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
