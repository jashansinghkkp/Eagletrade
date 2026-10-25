@echo off
title Insta Trade Terminal

echo ============================================================
echo                   Starting Insta Trade
echo             Fast and Simple Fyers Terminal
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 goto :no_python

if exist ".venv\Scripts\activate.bat" goto :activate_venv

echo [*] Creating virtual environment .venv...
python -m venv .venv
if errorlevel 1 goto :venv_error

:activate_venv
echo [*] Activating virtual environment...
call .venv\Scripts\activate.bat

python -c "import uvicorn, fastapi, httpx, dotenv" >nul 2>nul
if errorlevel 1 goto :install_deps
goto :start_server

:install_deps
echo [*] Installing dependencies... Please wait a moment.
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto :install_error

:start_server
echo.
echo ============================================================
echo Terminal URL:  http://127.0.0.1:8000
echo API Docs:      http://127.0.0.1:8000/docs
echo ============================================================
echo.
echo Launching browser...
ping 127.0.0.1 -n 2 >nul
start http://127.0.0.1:8000

echo Starting server...
uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
pause
exit /b 0

:no_python
echo [ERROR] Python is not installed or not in your PATH.
echo Please install Python 3.10 or newer from https://www.python.org/
echo Make sure to check the box "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:venv_error
echo [ERROR] Failed to create virtual environment.
echo.
pause
exit /b 1

:install_error
echo [ERROR] Failed to install dependencies.
echo.
pause
exit /b 1
