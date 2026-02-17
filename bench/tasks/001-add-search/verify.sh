#!/bin/bash
set -e

# Copy acceptance tests into workspace
cp "$(dirname "$0")/test_search.py" "$WORKSPACE/tests/test_search.py"

cd "$WORKSPACE"

# Run acceptance tests
echo "=== Acceptance Tests ==="
python -m pytest tests/test_search.py -v 2>&1
ACCEPT=$?

# Run regression tests
echo "=== Regression Tests ==="
python -m pytest tests/test_taskboard.py -v 2>&1
REGRESS=$?

exit $((ACCEPT + REGRESS))
