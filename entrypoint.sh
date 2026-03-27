#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# In a real-world scenario with Docker Compose, health checks or wait-for-it scripts
# are used to ensure the database is ready before the application starts.
# The 'depends_on' in docker-compose helps, but doesn't guarantee the DB is fully initialized.
# For simplicity, we'll proceed, but for robust production setups, consider adding a wait loop.

# The 'exec' command is important, it replaces the shell process with the Gunicorn process.
# This ensures that signals (like from 'docker stop') are passed correctly to Gunicorn.
echo "Starting Gunicorn server..."
exec gunicorn --bind 0.0.0.0:5000 --workers 4 "run:app" 