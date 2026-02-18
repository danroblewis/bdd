#!/bin/bash
set -euo pipefail

# bench/setup_subject_2.sh — Clone adk-playground, install deps, verify tests
# Run from bench/ directory: ./setup_subject_2.sh

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BENCH_DIR"

if [[ -d "subject_2" ]]; then
  echo "subject_2/ already exists. Remove it first to re-clone."
  echo "Skipping clone, checking venv..."
else
  echo "Cloning adk-playground..."
  git clone https://github.com/danroblewis/adk-playground subject_2
  cd subject_2

  # Remove large frontend dist to keep workspace small
  rm -rf frontend/dist .git .github

  cd "$BENCH_DIR"
  echo "Clone complete."
fi

# Create subject.json if missing
if [[ ! -f "subject_2/subject.json" ]]; then
  cat > subject_2/subject.json << 'EOF'
{
  "name": "adk_playground",
  "subject_dir": "subject_2",
  "tasks_dir": "tasks_2",
  "regression_test_file": "tests/",
  "regression_baseline": 81,
  "venv_python": ".venv_2/bin/python3"
}
EOF
  echo "Created subject_2/subject.json"
fi

# Create venv and install
if [[ ! -d ".venv_2" ]]; then
  echo "Creating .venv_2..."
  python3 -m venv .venv_2
  echo "Installing adk-playground dependencies..."
  .venv_2/bin/pip install -e "subject_2[dev]"
else
  echo ".venv_2 already exists."
fi

# Verify tests pass
echo ""
echo "Running tests..."
cd "$BENCH_DIR/subject_2"
../.venv_2/bin/python -m pytest tests/ -v --tb=short

echo ""
echo "Setup complete. subject_2 is ready."
