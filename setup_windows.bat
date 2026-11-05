@echo off
REM Stockfish Bridge - Setup Script for Windows
REM Automatically installs dependencies and sets up Stockfish engine

echo ========================================
echo   Stockfish Bridge - Windows Setup
echo ========================================
echo.

REM 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    echo   Download from: https://python.org/downloads/
    echo   Make sure to check "Add to PATH" during installation.
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo   Python: %%i

REM 2. Install Python dependencies
echo.
echo Installing Python dependencies...
pip install -r server\requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] Some dependencies failed to install. Continuing...
)

REM 3. Check and Resolve Stockfish Engine
echo.
echo Checking Stockfish engine...
set "STOCKFISH_FOUND="

if exist "server\bin\stockfish.exe" (
    echo   Stockfish: Found local binary in server\bin\stockfish.exe
    set "STOCKFISH_FOUND=server\bin\stockfish.exe"
) else (
    where stockfish >nul 2>&1
    if %errorlevel% equ 0 (
        for /f "tokens=*" %%i in ('where stockfish') do (
            echo   Stockfish: Found in PATH: %%i
            set "STOCKFISH_FOUND=%%i"
        )
    )
)

if "%STOCKFISH_FOUND%"=="" (
    echo   Stockfish not found locally or in PATH.
    echo   Attempting automatic download of latest verified Stockfish release...
    python server\downloader.py
    if exist "server\bin\stockfish.exe" (
        echo   [SUCCESS] Stockfish installed successfully to server\bin\stockfish.exe
        set "STOCKFISH_FOUND=server\bin\stockfish.exe"
    ) else (
        echo   [WARNING] Automated Stockfish download was not completed (offline or rate limited).
        echo   You can download Stockfish from https://stockfishchess.org/download/
        echo   and place stockfish.exe into server\bin\ folder.
    )
)

echo.
echo ========================================
echo   Setup complete!
echo ========================================
echo.
echo To start the bridge server:
echo   python start.py
echo.
pause
