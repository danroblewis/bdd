#!/bin/bash
# ADK Playground - Start script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 Starting ADK Playground..."
echo ""

# Check for Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18+ first."
    exit 1
fi

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.11+ first."
    exit 1
fi

# Setup backend
echo "📦 Setting up backend..."

if [ ! -d ".venv" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# Install dependencies if not already installed
if ! python -c "import fastapi" 2>/dev/null || ! python -c "import litellm" 2>/dev/null; then
    echo "  Installing dependencies..."
    pip install -q -e .
fi

echo "  Starting backend server on port 8080..."
cd backend
# Use the venv's python to ensure correct environment
../.venv/bin/python3 -m uvicorn main:app --port 8080 --host 0.0.0.0 &
BACKEND_PID=$!
cd ..

# Wait for backend to start
echo "  Waiting for backend to be ready..."
sleep 3

# Setup frontend
echo "📦 Setting up frontend..."
cd frontend

if [ ! -d "node_modules" ]; then
    echo "  Installing dependencies..."
    npm install --silent
fi

echo "  Starting frontend dev server on port 3000..."
npm run dev &
FRONTEND_PID=$!

cd ..

# Trap to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

echo ""
echo "✅ ADK Playground is running!"
echo ""
echo "   Frontend: http://localhost:3000"
echo "   Backend:  http://localhost:8080"
echo ""
echo "   Press Ctrl+C to stop"
echo ""

# Wait for processes
wait

