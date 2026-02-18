#!/bin/bash
set -e
cp "$(dirname "$0")/test_206_codegen_dry_run.py" "$WORKSPACE/tests/test_206_codegen_dry_run.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_206_codegen_dry_run.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/ --ignore=tests/test_206_codegen_dry_run.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
