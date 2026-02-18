#!/bin/bash
set -e
cp "$(dirname "$0")/test_204_project_tags.py" "$WORKSPACE/tests/test_204_project_tags.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_204_project_tags.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/ --ignore=tests/test_204_project_tags.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
