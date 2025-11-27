#!/bin/bash

# Start Redis if not already running
redis-cli ping > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Starting Redis server..."
    redis-server --daemonize yes --port 6379 --bind 127.0.0.1
    sleep 2
fi

# Start Celery worker and beat in the foreground
echo "Starting Celery worker and beat scheduler..."
celery -A celery_worker.celery worker --beat --loglevel=info --concurrency=4 --max-tasks-per-child=50
