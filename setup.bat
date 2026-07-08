@echo off
REM One-command setup for AI Job Applier (Windows)
REM Run from Command Prompt (not PowerShell) in the project folder.

echo.
echo ================================================
echo   AI Job Applier -- Setup
echo ================================================
echo.

REM ── 1. Install UV ────────────────────────────────────────────────────────────
where uv >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [*] Installing UV...
    pip install uv --quiet
    if %ERRORLEVEL% NEQ 0 (
        echo [!] pip install uv failed. Make sure Python is installed and on PATH.
        pause
        exit /b 1
    )
) else (
    echo [OK] UV already installed
)

REM ── 2. Create virtual environment ────────────────────────────────────────────
if not exist ".venv" (
    echo [*] Creating Python 3.11 virtual environment...
    uv venv --python 3.11
    if %ERRORLEVEL% NEQ 0 (
        echo [!] Failed to create virtual environment.
        echo     Make sure Python 3.11+ is installed from python.org
        pause
        exit /b 1
    )
) else (
    echo [OK] Virtual environment already exists
)

echo [*] Activating virtual environment...
call .venv\Scripts\activate.bat

REM ── 3. Install Python dependencies ───────────────────────────────────────────
echo [*] Installing Python packages (this may take 1-2 minutes)...
uv pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [!] Package installation failed.
    pause
    exit /b 1
)

REM ── 4. Install Playwright / Chromium ─────────────────────────────────────────
echo [*] Installing Chromium browser for automation...
playwright install chromium --with-deps
if %ERRORLEVEL% NEQ 0 (
    echo [!] Playwright install failed.
    pause
    exit /b 1
)

REM ── 5. Copy .env if missing ───────────────────────────────────────────────────
if not exist ".env" (
    copy .env.example .env >nul
    echo [*] Created .env from .env.example
) else (
    echo [OK] .env already exists
)

REM ── 6. Create tmp directories ─────────────────────────────────────────────────
if not exist "tmp\resumes" mkdir tmp\resumes
if not exist "tmp\agent_history" mkdir tmp\agent_history

echo.
echo ================================================
echo   Setup complete!
echo ================================================
echo.
echo Next steps:
echo   1. Open .env and fill in your API keys
echo      (or use the Key Setup tab in the UI)
echo.
echo   2. Start the app:
echo        .venv\Scripts\activate.bat
echo        python webui.py
echo.
echo   3. Open http://127.0.0.1:7788 in your browser
echo.
pause
