@echo off
:: ─────────────────────────────────────────────────────────────
::  test_curl.bat  –  Test semua endpoint YT Audio Player API
::  Jalankan dari Command Prompt:  test_curl.bat
::  Test group tertentu:           test_curl.bat tiktok
::  Multiple groups:               test_curl.bat player queue
::
::  Groups: info | search | queue | player | tiktok | overlay
::
::  Requires: curl (built-in di Windows 10+)
:: ─────────────────────────────────────────────────────────────
setlocal EnableDelayedExpansion

set BASE=http://localhost:8000
set TEST_URL=https://www.youtube.com/watch?v=dQw4w9WgXcQ
set PASS=0
set FAIL=0

:: Group filter (empty = run all)
set "FILTER=%~1"

echo.
echo =============================================
echo   YT Audio Player API -- Curl Test Suite
echo   Base: %BASE%
echo =============================================

:: ── Helper macro via goto ─────────────────────────────────────
:: call :REQ "Label" METHOD /path [body]

goto :MAIN

:REQ
  set "_label=%~1"
  set "_method=%~2"
  set "_path=%~3"
  set "_body=%~4"
  set "_url=%BASE%%_path%"

  if "%_body%"=="" (
    curl -s -o "%TEMP%\_resp.json" -w "%%{http_code}" -X %_method% -H "Content-Type: application/json" "%_url%" > "%TEMP%\_code.txt" 2>nul
  ) else (
    curl -s -o "%TEMP%\_resp.json" -w "%%{http_code}" -X %_method% -H "Content-Type: application/json" -d "%_body%" "%_url%" > "%TEMP%\_code.txt" 2>nul
  )

  set /p HTTP_CODE=<"%TEMP%\_code.txt"
  if not defined HTTP_CODE set HTTP_CODE=000

  if "!HTTP_CODE:~0,1!"=="2" (
    echo   [OK  !HTTP_CODE!]  !_label!
    set /a PASS+=1
  ) else (
    echo   [FAIL !HTTP_CODE!]  !_label!
    set /a FAIL+=1
    type "%TEMP%\_resp.json" 2>nul
    echo.
  )
  exit /b

:SHOULD_RUN
  :: Returns 0 (true) if FILTER is empty or matches %~1
  if "%FILTER%"=="" exit /b 0
  if /i "%FILTER%"=="%~1" exit /b 0
  :: check second arg too
  if /i "%~2"=="%~1" exit /b 0
  if /i "%~3"=="%~1" exit /b 0
  exit /b 1

:MAIN

:: ── INFO ──────────────────────────────────────────────────────
call :SHOULD_RUN info %FILTER%
if errorlevel 1 goto :SKIP_INFO
echo.
echo == INFO / ROOT ==
call :REQ "Root info"            GET  "/"
call :REQ "Player state"         GET  "/player/state"
call :REQ "MPV status"           GET  "/player/mpv/status"
call :REQ "TikTok status"        GET  "/tiktok/status"
call :REQ "Overlay state"        GET  "/overlay/state"
call :REQ "Overlay config"       GET  "/overlay/config"
call :REQ "Queue list"           GET  "/queue"
:SKIP_INFO

:: ── SEARCH ───────────────────────────────────────────────────
call :SHOULD_RUN search %FILTER%
if errorlevel 1 goto :SKIP_SEARCH
echo.
echo == SEARCH ==
call :REQ "Search keyword"  GET  "/search?q=never+gonna+give+you+up&limit=3"
call :REQ "Video info"      GET  "/info?url=https%%3A%%2F%%2Fwww.youtube.com%%2Fwatch%%3Fv%%3DdQw4w9WgXcQ"
call :REQ "Audio URL"       GET  "/audio/url?url=https%%3A%%2F%%2Fwww.youtube.com%%2Fwatch%%3Fv%%3DdQw4w9WgXcQ"
call :REQ "Curl cmd helper" GET  "/audio/curl-cmd?url=https%%3A%%2F%%2Fwww.youtube.com%%2Fwatch%%3Fv%%3DdQw4w9WgXcQ"
:SKIP_SEARCH

:: ── QUEUE ────────────────────────────────────────────────────
call :SHOULD_RUN queue %FILTER%
if errorlevel 1 goto :SKIP_QUEUE
echo.
echo == QUEUE MANAGEMENT ==
call :REQ "Add to queue"     POST  "/queue/add"     "{\"youtube_url\":\"%TEST_URL%\"}"
call :REQ "Get queue"        GET   "/queue"
call :REQ "Toggle shuffle"   POST  "/queue/shuffle"
call :REQ "Reorder (0->1)"   PUT   "/queue/reorder"  "{\"from_position\":0,\"to_position\":1}"
call :REQ "Remove pos 0"     DELETE "/queue/0"
call :REQ "Clear queue"      POST  "/queue/clear"
call :REQ "Queue after clear" GET  "/queue"
:SKIP_QUEUE

:: ── PLAYER ───────────────────────────────────────────────────
call :SHOULD_RUN player %FILTER%
if errorlevel 1 goto :SKIP_PLAYER
echo.
echo == PLAYER CONTROL ==
echo   [INFO] Playing song (takes a moment)...
call :REQ "Play now"         POST  "/player/play"    "{\"youtube_url\":\"%TEST_URL%\"}"
timeout /t 2 /nobreak >nul
call :REQ "Player state"     GET   "/player/state"
call :REQ "Pause"            POST  "/player/pause"
timeout /t 1 /nobreak >nul
call :REQ "Resume"           POST  "/player/resume"
timeout /t 1 /nobreak >nul
call :REQ "Add to queue"     POST  "/queue/add"      "{\"youtube_url\":\"%TEST_URL%\"}"
call :REQ "Next song"        POST  "/queue/next"
timeout /t 1 /nobreak >nul
call :REQ "Stop player"      POST  "/player/stop"
call :REQ "Stop MPV"         POST  "/player/mpv/stop"
call :REQ "State after stop" GET   "/player/state"
:SKIP_PLAYER

:: ── TIKTOK ───────────────────────────────────────────────────
call :SHOULD_RUN tiktok %FILTER%
if errorlevel 1 goto :SKIP_TIKTOK
echo.
echo == TIKTOK SIMULATE ==
call :REQ "TikTok status"            GET  "/tiktok/status"
call :REQ "Simulate #req"            POST "/tiktok/simulate?user=penonton1&comment=%%23req+never+gonna+give+you+up"
echo   [INFO] Menunggu yt-dlp search (3 detik)...
timeout /t 3 /nobreak >nul
call :REQ "Simulate #skip vote 1"    POST "/tiktok/simulate?user=penonton2&comment=%%23skip"
call :REQ "Simulate #skip vote 2"    POST "/tiktok/simulate?user=penonton3&comment=%%23skip"
call :REQ "Simulate #queue"          POST "/tiktok/simulate?user=penonton4&comment=%%23queue"
call :REQ "TikTok status (after)"    GET  "/tiktok/status"
:SKIP_TIKTOK

:: ── OVERLAY CONFIG ───────────────────────────────────────────
call :SHOULD_RUN overlay %FILTER%
if errorlevel 1 goto :SKIP_OVERLAY
echo.
echo == OBS OVERLAY CONFIG ==
call :REQ "Get overlay config"       GET "/overlay/config"
call :REQ "Get overlay state"        GET "/overlay/state"

echo   [INFO] Toggle request feed...
call :REQ "Hide request_feed"        PUT "/overlay/config"  "{\"show_request_feed\":false}"
timeout /t 1 /nobreak >nul
call :REQ "Show request_feed"        PUT "/overlay/config"  "{\"show_request_feed\":true}"

echo   [INFO] Ubah accent color...
call :REQ "Accent blue"              PUT "/overlay/config"  "{\"accent_color\":\"#3b82f6\"}"
timeout /t 1 /nobreak >nul
call :REQ "Accent orange (reset)"    PUT "/overlay/config"  "{\"accent_color\":\"#f97316\"}"

echo   [INFO] Pindah queue panel...
call :REQ "Queue panel left"         PUT "/overlay/config"  "{\"position_queue\":\"left\"}"
timeout /t 1 /nobreak >nul
call :REQ "Queue panel right"        PUT "/overlay/config"  "{\"position_queue\":\"right\"}"

call :REQ "Hide thumbnail"           PUT "/overlay/config"  "{\"show_thumbnail\":false}"
call :REQ "Hide skip vote"           PUT "/overlay/config"  "{\"show_skip_vote\":false}"
call :REQ "Restore all"              PUT "/overlay/config"  "{\"show_thumbnail\":true,\"show_skip_vote\":true}"

call :REQ "Font size 24px"           PUT "/overlay/config"  "{\"font_size_title\":24}"
call :REQ "Opacity 0.9"              PUT "/overlay/config"  "{\"opacity_panels\":0.9}"
call :REQ "Reset font+opacity"       PUT "/overlay/config"  "{\"font_size_title\":20,\"opacity_panels\":0.82}"
:SKIP_OVERLAY

:: ── Summary ──────────────────────────────────────────────────
echo.
echo =============================================
echo   PASS : %PASS%
echo   FAIL : %FAIL%
echo =============================================
if %FAIL%==0 (echo   Semua test passed!) else (echo   Ada test yang gagal.)
echo.
endlocal
