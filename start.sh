#!/usr/bin/env bash
# start.sh — Bootstrap launcher for the Chinese Anki Pipeline.
# Run this once (or any time); it sets up a virtualenv and launches the wizard.
set -e

cd "$(dirname "$0")"

# Check for Python 3.10+
if ! command -v python3 &>/dev/null; then
    echo "Python 3 not found. Install it from https://python.org and rerun this script."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(sys.version_info >= (3,10))")
if [ "$PY_VER" != "True" ]; then
    echo "Python 3.10 or newer is required. Current version:"
    python3 --version
    echo "Download a newer version from https://python.org"
    exit 1
fi

# Create virtualenv if missing
if [ ! -d ".venv" ]; then
    echo "Setting up Python environment (first run only) …"
    python3 -m venv .venv
fi

# Activate and install / upgrade deps quietly
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Launch the wizard
python pipeline.py wizard
