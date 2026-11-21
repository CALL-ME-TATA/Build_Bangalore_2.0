#!/usr/bin/env bash
# One-time project setup. Run from the repo root.
set -e
[ -d .git ] || git init
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e "./server[dev]"
[ -f .env ] || cp .env.example .env
echo "Done. Add your Gnani API key to .env, then see README.md to start the server."
