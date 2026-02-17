#!/bin/bash
set -e
cp "$(dirname "$0")/test_csv.py" "$WORKSPACE/tests/test_csv.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_csv.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/test_taskboard.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
