#!/bin/bash
set -e
cp "$(dirname "$0")/test_210_fix_callback_regen.py" "$WORKSPACE/tests/test_210_fix_callback_regen.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_210_fix_callback_regen.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/ --ignore=tests/test_210_fix_callback_regen.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
