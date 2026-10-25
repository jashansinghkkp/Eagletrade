#!/usr/bin/env python3
"""
Insta Trade Launcher (start.py)
Cross-platform launcher for Insta Trade.
"""

import sys
import subprocess
import webbrowser
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / ".venv"

if sys.platform == "win32":
    VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
    VENV_PIP = VENV_DIR / "Scripts" / "pip.exe"
else:
    VENV_PYTHON = VENV_DIR / "bin" / "python"
    VENV_PIP = VENV_DIR / "bin" / "pip"


def main():
    print("=" * 60)
    print("                 Starting Insta Trade Terminal")
    print("           (Fast & Simple Fyers Trading Terminal)")
    print("=" * 60)

    # 1. Setup Virtual Environment
    if not VENV_DIR.exists():
        print("[*] Creating Python virtual environment (.venv)...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    # 2. Check and install dependencies
    check_code = "import uvicorn, fastapi, httpx, dotenv"
    res = subprocess.run([str(VENV_PYTHON), "-c", check_code], capture_output=True)
    if res.returncode != 0:
        print("[*] Installing lightweight requirements...")
        subprocess.run([str(VENV_PIP), "install", "-r", "requirements.txt"], cwd=ROOT_DIR, check=True)

    # 3. Start server
    print("\n" + "=" * 60)
    print("Insta Trade Terminal: http://127.0.0.1:8000")
    print("Interactive API Docs: http://127.0.0.1:8000/docs")
    print("=" * 60 + "\n")
    print("Opening browser...")
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:8000")

    try:
        subprocess.run(
            [str(VENV_PYTHON), "-m", "uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
            cwd=ROOT_DIR,
        )
    except KeyboardInterrupt:
        print("\n[*] Insta Trade stopped.")


if __name__ == "__main__":
    main()
