#!/bin/bash
set -e
cp "$(dirname "$0")/test_201_duplicate_project.py" "$WORKSPACE/tests/test_201_duplicate_project.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_201_duplicate_project.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/ --ignore=tests/test_201_duplicate_project.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
