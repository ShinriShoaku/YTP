@echo off
REM build.bat – Build YTPlayer standalone for Windows
REM Usage:  Double-click or run from Developer Command Prompt
setlocal enabledelayedexpansion

set DIST_NAME=YTPlayer
set DIST_DIR=dist\%DIST_NAME%

echo ============================================
echo   YTPlayer Windows Build
echo ============================================

REM ── 1. Check Python ─────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python not found. Install Python 3.10+ and add to PATH.
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo [INFO] Using %%i

REM ── 2. Virtual-env ──────────────────────────────────────────
if not exist ".venv" (
    echo [INFO] Creating virtualenv...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

REM ── 3. Install deps ─────────────────────────────────────────
echo [INFO] Installing dependencies...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
python -m pip install pyinstaller -q

REM ── 4. Clean previous build ─────────────────────────────────
echo [INFO] Cleaning previous build...
if exist build     rmdir /s /q build
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"

REM ── 5. PyInstaller ──────────────────────────────────────────
echo [INFO] Running PyInstaller...
pyinstaller ytplayer.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERROR] PyInstaller failed.
    pause & exit /b 1
)

REM ── 6. Assemble final folder ─────────────────────────────────
echo [INFO] Assembling output...
mkdir "%DIST_DIR%\overlays" 2>nul
mkdir "%DIST_DIR%\mpv"      2>nul
mkdir "%DIST_DIR%\assets"   2>nul

REM Copy binary
copy "dist\YTPlayer.exe" "%DIST_DIR%\YTPlayer.exe" >nul

REM Copy overlay HTML files
for %%f in (obs_overlay.html obs_nowplaying.html obs_queue.html ^
            obs_commands.html obs_subtitle.html obs_requests.html) do (
    if exist "%%f" (
        copy "%%f" "%DIST_DIR%\overlays\%%f" >nul
        echo   + overlays\%%f
    )
)

REM Copy config / queue stubs
if not exist "%DIST_DIR%\config.json" copy config.json "%DIST_DIR%\config.json" >nul
if not exist "%DIST_DIR%\queue.json"  echo [] > "%DIST_DIR%\queue.json"

REM Copy assets
if exist assets xcopy /e /q /y assets "%DIST_DIR%\assets\" >nul

REM Check for mpv.exe
echo.
if exist "mpv\mpv.exe" (
    copy "mpv\mpv.exe" "%DIST_DIR%\mpv\mpv.exe" >nul
    echo [OK] mpv.exe bundled from mpv\mpv.exe
) else (
    echo [WARN] mpv\mpv.exe not found.
    echo        Download mpv from https://mpv.io/installation/
    echo        and place mpv.exe in: %DIST_DIR%\mpv\mpv.exe
)

echo.
echo ============================================
echo   Build complete!
echo   Output: %DIST_DIR%\
echo   Run:    %DIST_DIR%\YTPlayer.exe
echo ============================================
pause
