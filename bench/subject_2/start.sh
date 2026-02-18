#!/bin/bash
# Start script for ADK Playground
# Supports both dev mode (2 servers) and production mode (1 server)

set -e

# Check mode from environment variable
MODE=${ADK_PLAYGROUND_MODE:-dev}

# Check if virtualenv exists
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Please run ./setup.sh first."
    exit 1
fi

# Activate virtualenv
source .venv/bin/activate

# Check Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
REQUIRED_VERSION="3.10"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Warning: Python 3.10+ is required. You have Python $PYTHON_VERSION"
    echo "The application may not work correctly."
fi

if [ "$MODE" = "production" ]; then
    # Production mode: single server with static assets
    echo "Starting ADK Playground in PRODUCTION mode..."
    echo ""
    
    # Check if frontend is built
    if [ ! -d "frontend/dist" ]; then
        echo "Error: Frontend not built. Run ./build.sh first."
        exit 1
    fi
    
    echo "Backend with static assets will run on http://localhost:8080"
    echo ""
    echo "Press Ctrl+C to stop the server"
    echo ""
    
    export ADK_PLAYGROUND_MODE=production
    cd backend
    uvicorn main:app --port 8080 --host 0.0.0.0
else
    # Dev mode: separate servers
    echo "Starting ADK Playground in DEV mode..."
echo ""
echo "Backend will run on http://localhost:8080"
echo "Frontend will run on http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop all servers"
echo ""

# Start backend in background
cd backend
uvicorn main:app --port 8080 --host 0.0.0.0 &
BACKEND_PID=$!
cd ..

# Start frontend in background
cd frontend
    if [ ! -d "node_modules" ]; then
        echo "Installing frontend dependencies..."
        npm install
    fi
npm run dev &
FRONTEND_PID=$!
cd ..

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Stopping servers..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}

# Trap Ctrl+C
trap cleanup INT TERM

# Wait for both processes
wait
fi

