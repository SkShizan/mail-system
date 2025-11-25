#!/bin/bash
redis-server --daemonize yes --port 6379 --bind 127.0.0.1
echo "Redis server started on port 6379"
