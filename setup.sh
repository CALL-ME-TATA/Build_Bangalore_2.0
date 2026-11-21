#!/usr/bin/env bash
# One-time project setup. Run from the repo root.
set -e
[ -d .git ] || git init
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e "./server[dev]"
[ -f .env ] || cp .env.example .env
if command -v npm >/dev/null 2>&1; then
  (cd frontend && npm ci && npm run build)
else
  echo "Node was not found. The server will serve the earlier client in web/. For the main web app, install Node and run 'npm ci' and 'npm run build' in frontend/."
fi
echo "Done. Add your Gnani API key to .env, then see README.md to start the server."
