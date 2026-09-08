#!/usr/bin/env bash
# Idempotent Cloud Agent install for AI Job Applier.
# Mirrors setup.sh but tuned for a non-interactive build/snapshot environment.
set -euo pipefail

cd "$(dirname "$0")/.."

# 1. Ensure uv (fast Python package manager) is on PATH.
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv..."
    pip install --user uv
fi
uv --version

# 2. Create the Python 3.11 virtual environment (guarded for idempotence).
if [ ! -d ".venv" ]; then
    echo "Creating Python 3.11 virtual environment..."
    uv venv --python 3.11
else
    echo "Virtual environment already exists."
fi

# 3. Install Python dependencies into the venv.
echo "Installing Python dependencies..."
uv pip install --python .venv/bin/python -r requirements.txt

# 4. Install the Chromium browser Playwright drives (with OS deps).
echo "Installing Playwright Chromium..."
.venv/bin/playwright install chromium --with-deps

# 5. Seed .env from the example if it doesn't exist yet.
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
fi

# 6. Create runtime scratch directories.
mkdir -p tmp/resumes tmp/agent_history

echo "Install complete."
