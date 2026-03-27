#!/bin/bash
#!/usr/bin/env bash

export HF_HOME="$(pwd)/models"
export HF_HUB_LOCAL_DIR="$HF_HOME"
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
export UNSTRUCTURED_LOCAL_INFERENCE=1

set -e # Exit immediately if a command exits with a non-zero status.

# --- Prerequisite Check ---
echo "--- Checking Prerequisites ---"

# 1. Check for Redis
echo "Checking for running Redis server..."
if ! redis-cli ping > /dev/null 2>&1; then
    echo "🔴 Redis server not found or not running."
    echo "Please install Redis and start it before running this script."
    echo "On Debian/Ubuntu: sudo apt-get install redis-server && sudo systemctl start redis-server"
    echo "On macOS: brew install redis && brew services start redis"
    exit 1
else
    echo "✅ Redis server is running."
fi

# 2. Check for Python environment
echo "Checking for Python virtual environment..."
if [ -z "$VIRTUAL_ENV" ]; then
    echo "🟡 It's recommended to run this project in a Python virtual environment."
    echo "To create one: python3 -m venv venv && source venv/bin/activate"
fi

# --- Dependency Installation ---
# echo -e "\n--- Setting up Python Dependencies ---"
# echo "Installing/updating dependencies from requirements.txt..."
# pip install -r requirements.txt
# echo "✅ Dependencies are up to date."

# --- Service Startup ---
echo -e "\n--- Starting Services ---"

# Function to clean up background processes
cleanup() {
    echo -e "\n🚨 Shutting down services..."
    # The `-` before the PID sends the signal to the entire process group, ensuring child processes of celery also get terminated.
    if [ -n "$celery_pid" ]; then
        echo "Stopping Celery worker (PGID: $celery_pid)..."
        # Send SIGTERM to the entire process group. No quotes around -$celery_pid.
        # This ensures the main process and all its forked workers are terminated.
        # Redirect stderr to /dev/null to avoid messages if process is already gone.
        kill -TERM -$celery_pid 2>/dev/null || true
        echo "Celery worker stopped."
    fi
    if [ -n "$flask_pid" ]; then
        echo "Stopping Flask server (PID: $flask_pid)..."
        kill -TERM $flask_pid 2>/dev/null || true
        echo "Flask server stopped."
    fi
}

# Trap Ctrl+C (SIGINT) and other termination signals to run the cleanup function.
# The `exit` command was removed from cleanup() to avoid issues with the EXIT trap.
trap cleanup SIGINT SIGTERM EXIT

# Set monitoring to kill child processes
set -m

# Start Flask server in the background
echo "Starting Flask server on http://127.0.0.1:5000 ..."
flask run &
flask_pid=$!

# Start Celery worker in the background
echo "Starting Celery worker..."
celery -A celery_worker.celery_app worker --loglevel=info &
celery_pid=$!

echo -e "\n✅ All services are running in the background."
echo "   - Flask PID: $flask_pid"
echo "   - Celery PID: $celery_pid"
echo -e "\n🚀 Application is ready! Press Ctrl+C to stop all services."

# Wait for background processes to finish. The trap will handle the exit.
wait 