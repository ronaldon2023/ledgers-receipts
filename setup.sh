#!/usr/bin/env bash
# One-time setup: virtualenv, dependencies, git hook.
set -euo pipefail

if ! command -v python3.12 >/dev/null; then
  echo "Python 3.12 is required. Install it, then rerun ./setup.sh"
  exit 1
fi

python3.12 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
# Small spaCy model for Presidio (13 MB). The default large one is ~400 MB.
.venv/bin/python -m spacy download en_core_web_sm --quiet

git config core.hooksPath .githooks
chmod +x .githooks/pre-commit

echo "Setup done. Run: make test"
