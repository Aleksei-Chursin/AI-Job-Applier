#!/usr/bin/env bash
# One-command setup for AI Job Applier (Mac / Linux)
set -euo pipefail

echo ""
echo "================================================"
echo "  AI Job Applier — Setup"
echo "================================================"
echo ""

# ── 1. Install UV (fast Python package manager) ──────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "📦 Installing UV..."
    pip install uv --quiet
else
    echo "✅ UV already installed ($(uv --version))"
fi

# ── 2. Create virtual environment with Python 3.11 ───────────────────────────
if [ ! -d ".venv" ]; then
    echo "🐍 Creating Python 3.11 virtual environment..."
    uv venv --python 3.11
else
    echo "✅ Virtual environment already exists"
fi

echo "🔄 Activating virtual environment..."
# shellcheck disable=SC1091
source .venv/bin/activate

# ── 3. Install Python dependencies ───────────────────────────────────────────
echo "📦 Installing Python packages (this may take 1–2 minutes)..."
uv pip install -r requirements.txt --quiet

# ── 4. Install Playwright / Chromium browser ─────────────────────────────────
echo "🌐 Installing Chromium browser for automation..."
playwright install chromium --with-deps

# ── 5. Copy .env if it doesn't exist ─────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "📋 Created .env from .env.example"
else
    echo "✅ .env already exists"
fi

# ── 6. Create tmp directories ────────────────────────────────────────────────
mkdir -p tmp/resumes tmp/agent_history

echo ""
echo "================================================"
echo "  ✅  Setup complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "  1. Open .env and fill in your API keys"
echo "     (or use the 🔑 Setup tab in the UI)"
echo ""
echo "  2. Start the app:"
echo "       source .venv/bin/activate"
echo "       python webui.py"
echo ""
echo "  3. Open http://127.0.0.1:7788 in your browser"
echo ""
echo "  Tip: add this alias to ~/.zshrc for quick restarts:"
echo "    alias jobapply=\"cd $(pwd) && source .venv/bin/activate && python webui.py\""
echo ""
