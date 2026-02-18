#!/bin/bash
set -e
cp "$(dirname "$0")/test_209_project_export_zip.py" "$WORKSPACE/tests/test_209_project_export_zip.py"
cd "$WORKSPACE"
echo "=== Acceptance Tests ==="
python -m pytest tests/test_209_project_export_zip.py -v 2>&1
ACCEPT=$?
echo "=== Regression Tests ==="
python -m pytest tests/ --ignore=tests/test_209_project_export_zip.py -v 2>&1
REGRESS=$?
exit $((ACCEPT + REGRESS))
