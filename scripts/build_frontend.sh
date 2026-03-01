#!/bin/bash
# Run this script before pushing to Azure to build the frontend.
# Usage: bash scripts/build_frontend.sh
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Building frontend..."
cd "$PROJECT_ROOT/frontend"
npm ci
npm run build

echo "Copying build output to backend/app/static/..."
rm -rf "$PROJECT_ROOT/backend/app/static"
mkdir -p "$PROJECT_ROOT/backend/app/static"
cp -r dist/* "$PROJECT_ROOT/backend/app/static/"

echo ""
echo "Done! Frontend built and ready to deploy."
echo ""
echo "Next steps:"
echo "  git add backend/app/static/"
echo "  git commit -m 'deploy: build frontend'"
echo "  git push azure master"
