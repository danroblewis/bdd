#!/bin/bash
set -e
cp "$(dirname "$0")/test_207_eval_comparison.py" "$WORKSPACE/tests/test_207_eval_comparison.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_207_eval_comparison.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/ --ignore=tests/test_207_eval_comparison.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
