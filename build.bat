@echo off
REM build.bat – Build YTPlayer (ONE-DIR mode) for Windows
REM One-dir: YTPlayer.exe = launcher, libs in _internal/ → fewer AV false positives
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "EXE_NAME=YTPlayer"
set "DIST_DIR=%SCRIPT_DIR%dist\%EXE_NAME%"

echo ============================================
echo   YTPlayer Windows Build  [one-dir mode]
echo ============================================

REM ── 1. Check Python ─────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] python not found. Install Python 3.10+ and add to PATH.
    goto :fail
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo [INFO] %%i

REM ── 2. Virtual-env ──────────────────────────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] Creating virtualenv...
    python -m venv .venv
    if %errorlevel% neq 0 ( echo [ERROR] venv creation failed. & goto :fail )
)
echo [INFO] Activating virtualenv...
call ".venv\Scripts\activate.bat"

REM ── 3. Install deps ─────────────────────────────────────────
echo [INFO] Installing dependencies...
python -m pip install --upgrade pip --quiet
if %errorlevel% neq 0 ( echo [ERROR] pip upgrade failed. & goto :fail )

python -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 ( echo [ERROR] requirements install failed. & goto :fail )

python -m pip install pyinstaller pillow --quiet
if %errorlevel% neq 0 ( echo [ERROR] pyinstaller/pillow install failed. & goto :fail )

REM ── 4. Generate icon ────────────────────────────────────────
echo [INFO] Generating icon...
if not exist "assets" mkdir assets
python make_icon.py
if %errorlevel% neq 0 ( echo [WARN] Icon generation failed, continuing without icon. )

REM ── 5. Clean previous build ─────────────────────────────────
echo [INFO] Cleaning previous build...
if exist "build"      rmdir /s /q "build"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"

REM ── 6. PyInstaller (one-dir) ────────────────────────────────
echo [INFO] Running PyInstaller ^(one-dir mode^)...
pyinstaller ytplayer.spec --noconfirm --clean
if %errorlevel% neq 0 ( echo [ERROR] PyInstaller failed. & goto :fail )

REM Verify PyInstaller created the folder
if not exist "%DIST_DIR%\%EXE_NAME%.exe" (
    echo [ERROR] %DIST_DIR%\%EXE_NAME%.exe not found after build!
    goto :fail
)
echo [OK] %EXE_NAME%.exe built successfully.

REM ── 7. Inject overlays, config, mpv into dist folder ────────
echo [INFO] Adding overlays and config...

if not exist "%DIST_DIR%\overlays" mkdir "%DIST_DIR%\overlays"
if not exist "%DIST_DIR%\mpv"      mkdir "%DIST_DIR%\mpv"
if not exist "%DIST_DIR%\assets"   mkdir "%DIST_DIR%\assets"

REM Overlay HTML files
for %%f in (obs_overlay obs_nowplaying obs_queue obs_commands obs_subtitle obs_requests) do (
    if exist "%%f.html" (
        copy /y "%%f.html" "%DIST_DIR%\overlays\%%f.html" >nul
        echo   + overlays\%%f.html
    ) else (
        echo   [WARN] %%f.html not found
    )
)

REM config.json – don't overwrite if user already has one in dist
if not exist "%DIST_DIR%\config.json" (
    copy /y "config.json" "%DIST_DIR%\config.json" >nul
    echo   + config.json
)

REM queue.json – use Python to avoid CMD echo adding BOM/spaces
if not exist "%DIST_DIR%\queue.json" (
    python -c "open(r'%DIST_DIR%\queue.json','w').write('[]')"
    echo   + queue.json
)

REM assets (icon etc.)
if exist "assets" (
    xcopy /e /i /q /y "assets" "%DIST_DIR%\assets\" >nul
    echo   + assets\
)

REM ── 8. Bundle mpv.exe ────────────────────────────────────────
echo.
if exist "mpv\mpv.exe" (
    copy /y "mpv\mpv.exe" "%DIST_DIR%\mpv\mpv.exe" >nul
    echo [OK] mpv.exe bundled.
) else (
    echo [WARN] mpv\mpv.exe not found.
    echo        Download: https://mpv.io/installation/ ^(Windows build^)
    echo        Place at: mpv\mpv.exe  then re-run build.
)

REM ── 9. Summary ───────────────────────────────────────────────
echo.
echo ============================================
echo   Build complete!  [one-dir]
echo.
echo   Output  : %DIST_DIR%\
echo   Run     : %DIST_DIR%\%EXE_NAME%.exe
echo.
echo   Structure:
echo     %EXE_NAME%.exe       ^<-- launcher
echo     _internal\       ^<-- Python libs ^(AV friendly^)
echo     overlays\        ^<-- OBS HTML files
echo     config.json
echo     mpv\mpv.exe
echo ============================================
goto :end

:fail
echo.
echo [BUILD FAILED] See errors above.
echo ============================================
pause
exit /b 1

:end
pause
