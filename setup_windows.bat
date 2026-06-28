@echo off
REM Stockfish Bridge - Setup Script for Windows
REM Run this script in Command Prompt to verify setup

echo ========================================
echo   Stockfish Bridge - Windows Setup
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    echo   Download from: https://python.org/downloads/
    echo   Make sure to check "Add to PATH" during installation.
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo   Python: %%i

REM Check Stockfish
where stockfish >nul 2>&1
if %errorlevel% neq 0 (
    echo   Stockfish: NOT FOUND in PATH
    echo.
    echo   Download Stockfish from: https://stockfishchess.org/download/
    echo   Extract and add the folder to your PATH, or specify the path:
    echo     python server\bridge.py --stockfish-path "C:\path\to\stockfish.exe"
    echo.
) else (
    for /f "tokens=*" %%i in ('where stockfish') do echo   Stockfish: %%i
)

REM Install Python dependencies
echo.
echo Installing Python dependencies...
pip install -r server\requirements.txt

echo.
echo ========================================
echo   Setup complete!
echo ========================================
echo.
echo To start the bridge server:
echo   python server\bridge.py
echo.
echo With custom Stockfish path:
echo   python server\bridge.py --stockfish-path "C:\path\to\stockfish.exe" --threads 8 --hash 2048
echo.
pause
