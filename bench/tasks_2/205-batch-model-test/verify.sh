#!/bin/bash
set -e
cp "$(dirname "$0")/test_205_batch_model_test.py" "$WORKSPACE/tests/test_205_batch_model_test.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_205_batch_model_test.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/ --ignore=tests/test_205_batch_model_test.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
