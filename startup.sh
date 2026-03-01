#!/bin/bash
set -e

# Ensure persistent data directory exists
mkdir -p /home/data

# Run from backend directory so app imports resolve correctly
cd /home/site/wwwroot/backend

exec gunicorn \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  app.main:app \
  --bind 0.0.0.0:${PORT:-8000} \
  --timeout 120 \
  --access-logfile '-' \
  --error-logfile '-'
