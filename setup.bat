@echo off
REM One-command setup for AI Job Applier (Windows)
REM Run from Command Prompt (not PowerShell) in the project folder.

echo.
echo ================================================
echo   AI Job Applier -- Setup
echo ================================================
echo.

REM ── Detect Python ────────────────────────────────────────────────────────────
REM Try 'py' (Python Launcher, default on Windows), then 'python'.
set PYTHON_CMD=
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 set PYTHON_CMD=py
if "%PYTHON_CMD%"=="" (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 set PYTHON_CMD=python
)
if "%PYTHON_CMD%"=="" (
    echo [!] Python not found on PATH.
    echo     Download and install Python 3.11+ from https://python.org
    echo     During install, check "Add Python to PATH".
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('%PYTHON_CMD% --version 2^>^&1') do set PYTHON_VER=%%v
echo [OK] Found %PYTHON_VER% (command: %PYTHON_CMD%)

REM ── Add system Python's Scripts dir to PATH so uv is reachable after venv activation ──
REM  (The 'py' launcher respects VIRTUAL_ENV and switches to the venv Python after
REM  activation, making 'py -m uv' fail. Using the bare 'uv' command via PATH avoids this.)
for /f "tokens=*" %%p in ('%PYTHON_CMD% -c "import sysconfig; print(sysconfig.get_path(\"scripts\"))"') do set SYS_SCRIPTS=%%p
set PATH=%SYS_SCRIPTS%;%PATH%
echo [OK] Added Python Scripts to PATH: %SYS_SCRIPTS%

REM ── Install UV ────────────────────────────────────────────────────────────────
where uv >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=*" %%v in ('uv --version 2^>^&1') do set UV_VER=%%v
    echo [OK] UV already installed ^(%UV_VER%^)
    goto :uv_ready
)

echo [*] Installing UV...
%PYTHON_CMD% -m pip install uv --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [!] Failed to install UV.
    echo     Try: %PYTHON_CMD% -m pip install --upgrade pip   then re-run this script.
    pause
    exit /b 1
)
echo [OK] UV installed.

:uv_ready

REM ── Create virtual environment ────────────────────────────────────────────────
if not exist ".venv" (
    echo [*] Creating Python 3.11 virtual environment...
    uv venv --python 3.11
    if %ERRORLEVEL% NEQ 0 (
        echo [!] Failed to create virtual environment.
        echo     Make sure Python 3.11+ is installed: https://python.org
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists.
)

REM ── Activate virtual environment ──────────────────────────────────────────────
echo [*] Activating virtual environment...
call .venv\Scripts\activate.bat
if %ERRORLEVEL% NEQ 0 (
    echo [!] Could not activate virtual environment.
    echo     Delete the .venv folder and re-run this script.
    pause
    exit /b 1
)
echo [OK] Virtual environment active.

REM ── Install Python dependencies ───────────────────────────────────────────────
REM  uv is now reachable via the system Scripts dir we added to PATH above.
echo [*] Installing Python packages (this may take 1-2 minutes)...
uv pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [!] Package installation failed.
    echo     Check your internet connection and try again.
    pause
    exit /b 1
)
echo [OK] Packages installed.

REM ── Install Playwright / Chromium ─────────────────────────────────────────────
echo [*] Installing Chromium browser for automation...
playwright install chromium --with-deps
if %ERRORLEVEL% NEQ 0 (
    echo [!] Playwright/Chromium install failed.
    echo     Try running manually: playwright install chromium --with-deps
    pause
    exit /b 1
)
echo [OK] Chromium installed.

REM ── Copy .env if missing ───────────────────────────────────────────────────────
if not exist ".env" (
    copy .env.example .env >nul
    echo [*] Created .env from .env.example
) else (
    echo [OK] .env already exists.
)

REM ── Create tmp directories ─────────────────────────────────────────────────────
if not exist "tmp" mkdir tmp
if not exist "tmp\resumes" mkdir tmp\resumes
if not exist "tmp\agent_history" mkdir tmp\agent_history
echo [OK] tmp\ directories ready.

echo.
echo ================================================
echo   Setup complete!
echo ================================================
echo.
echo Next steps:
echo   1. Start the app:
echo        .venv\Scripts\activate.bat
echo        python webui.py
echo.
echo   2. Open http://127.0.0.1:7788 in your browser
echo      Use the "Key Setup" tab to fill in your API keys.
echo.
pause
