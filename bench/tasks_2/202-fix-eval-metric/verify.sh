#!/bin/bash
set -e
cp "$(dirname "$0")/test_202_eval_metric.py" "$WORKSPACE/tests/test_202_eval_metric.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_202_eval_metric.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/ --ignore=tests/test_202_eval_metric.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
