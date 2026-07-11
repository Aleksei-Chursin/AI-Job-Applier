#!/usr/bin/env python3
"""
Start the AI Job Applier — works on Windows, Mac, and Linux.

Usage:
    python start.py
    python start.py --port 8080
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# Venv Python path differs by OS
VENV_PYTHON = ROOT / (
    ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"
)

if not VENV_PYTHON.exists():
    print()
    print("❌  Virtual environment not found.")
    print()
    if sys.platform == "win32":
        print("   Run setup first:  .\\setup.bat")
    else:
        print("   Run setup first:  ./setup.sh")
    print()
    sys.exit(1)

print("🚀  Starting AI Job Applier…")
print(f"    Python : {VENV_PYTHON}")
print(f"    Open   : http://127.0.0.1:7788")
print()

try:
    subprocess.run([str(VENV_PYTHON), str(ROOT / "webui.py")] + sys.argv[1:])
except KeyboardInterrupt:
    pass
