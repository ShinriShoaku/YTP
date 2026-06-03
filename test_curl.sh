#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  test_curl.sh  –  Test semua endpoint YT Audio Player API
#  Usage:
#    bash test_curl.sh               → jalankan semua test
#    bash test_curl.sh search        → test group tertentu
#    bash test_curl.sh player queue  → beberapa group sekaligus
#
#  Groups: info | search | queue | player | tiktok | overlay
# ─────────────────────────────────────────────────────────────

BASE="http://localhost:8000"
PASS=0; FAIL=0; SKIP=0

# Contoh URL YouTube untuk testing (lagu pendek)
TEST_URL="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
TEST_QUERY="never gonna give you up rickroll"

# ── Warna terminal ────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

header() { echo -e "\n${BOLD}${CYAN}══ $1 ══${NC}"; }
ok()     { echo -e "  ${GREEN}✓${NC}  $1"; ((PASS++)); }
fail()   { echo -e "  ${RED}✗${NC}  $1"; ((FAIL++)); }
info()   { echo -e "  ${YELLOW}→${NC}  $1"; }

# ── Helper: run curl, check HTTP status ──────────────────────
# Usage: req <LABEL> <METHOD> <PATH> [BODY_JSON]
req() {
  local label="$1" method="$2" path="$3" body="$4"
  local args=(-s -o /tmp/_resp.json -w "%{http_code}" -X "$method")
  args+=(-H "Content-Type: application/json")
  [[ -n "$body" ]] && args+=(-d "$body")
  local code
  code=$(curl "${args[@]}" "$BASE$path")
  local resp
  resp=$(cat /tmp/_resp.json 2>/dev/null)
  if [[ "$code" =~ ^2 ]]; then
    ok "[$code] $label"
    # Pretty print key fields if jq available
    if command -v jq &>/dev/null; then
      echo "$resp" | jq -r '
        if   .title        then "        title: \(.title)"
        elif .song.title   then "        song:  \(.song.title)"
        elif .message      then "        msg:   \(.message)"
        elif .current_song then "        now:   \(.current_song.title // "—")"
        else empty end' 2>/dev/null
    fi
  else
    fail "[$code] $label"
    info "Response: $(echo "$resp" | head -c 200)"
  fi
}

# ── Filter: run only requested groups ────────────────────────
RUN_GROUPS=("$@")
should_run() {
  [[ ${#RUN_GROUPS[@]} -eq 0 ]] && return 0
  for g in "${RUN_GROUPS[@]}"; do [[ "$g" == "$1" ]] && return 0; done
  return 1
}

echo -e "\n${BOLD}YT Audio Player API — Curl Test Suite${NC}"
echo -e "Base URL : ${CYAN}$BASE${NC}"
echo -e "Test URL : ${YELLOW}$TEST_URL${NC}"

# ────────────────────────────────────────────────────────────
#  GROUP: info
# ────────────────────────────────────────────────────────────
if should_run info; then
  header "INFO / ROOT"
  req "Root info"            GET  "/"
  req "API Docs"             GET  "/docs"
  req "Player state"         GET  "/player/state"
  req "MPV status"           GET  "/player/mpv/status"
  req "TikTok status"        GET  "/tiktok/status"
  req "Overlay state"        GET  "/overlay/state"
  req "Overlay config"       GET  "/overlay/config"
  req "Queue list"           GET  "/queue"
fi

# ────────────────────────────────────────────────────────────
#  GROUP: search
# ────────────────────────────────────────────────────────────
if should_run search; then
  header "SEARCH"
  req "Search keyword"       GET  "/search?q=$(python3 -c "import urllib.parse;print(urllib.parse.quote('$TEST_QUERY'))")&limit=3"
  req "Video info"           GET  "/info?url=$(python3 -c "import urllib.parse;print(urllib.parse.quote('$TEST_URL'))")"
  req "Audio URL (no play)"  GET  "/audio/url?url=$(python3 -c "import urllib.parse;print(urllib.parse.quote('$TEST_URL'))")"
  req "Curl command helper"  GET  "/audio/curl-cmd?url=$(python3 -c "import urllib.parse;print(urllib.parse.quote('$TEST_URL'))")"

  header "SUBTITLE"
  info "Subtitle by URL (tidak perlu lagu playing)"
  req "Subtitle languages (URL)" GET  "/subtitles?url=$(python3 -c "import urllib.parse;print(urllib.parse.quote('$TEST_URL'))")&lang=en"
  info "Subtitle current – membutuhkan lagu sedang playing (skip jika idle)"
  # Play dulu sementara, ambil subtitle, lalu stop
  curl -s -o /dev/null -X POST -H "Content-Type: application/json" \
    -d "{\"youtube_url\":\"$TEST_URL\"}" "$BASE/player/play" && sleep 1
  req "List subtitles (current)"  GET "/subtitles/list"
  req "Subtitle current en"       GET "/subtitles/current?lang=en"
  curl -s -o /dev/null -X POST "$BASE/player/stop"
fi

# ────────────────────────────────────────────────────────────
#  GROUP: queue
# ────────────────────────────────────────────────────────────
if should_run queue; then
  header "QUEUE MANAGEMENT"

  info "Clear queue dulu biar state bersih..."
  curl -s -o /dev/null -X POST "$BASE/queue/clear"
  curl -s -o /dev/null -X POST "$BASE/player/stop"

  info "Tambah 2 lagu ke queue..."
  req "Add song #1"          POST "/queue/add"      "{\"youtube_url\":\"$TEST_URL\"}"
  req "Add song #2 (search)" POST "/search/add-top?q=$(python3 -c "import urllib.parse;print(urllib.parse.quote('shape of you ed sheeran'))")"
  req "Get queue (2 songs)"  GET  "/queue"

  req "Toggle shuffle"       POST "/queue/shuffle"
  req "Toggle shuffle OFF"   POST "/queue/shuffle"

  info "Reorder: pindah posisi 0 → 1 (butuh 2+ lagu)"
  req "Reorder (0 → 1)"      PUT  "/queue/reorder"  '{"from_position":0,"to_position":1}'
  req "Swap pos 0 ↔ 1"       PUT  "/queue/swap"      '{"position_a":0,"position_b":1}'

  req "Remove position 0"    DELETE "/queue/0"
  req "Queue after remove"   GET  "/queue"
  req "Clear queue"          POST "/queue/clear"
  req "Queue after clear"    GET  "/queue"
fi

# ────────────────────────────────────────────────────────────
#  GROUP: player
# ────────────────────────────────────────────────────────────
if should_run player; then
  header "PLAYER CONTROL"

  info "Playing song... (takes a few seconds)"
  req "Play now"             POST "/player/play"    "{\"youtube_url\":\"$TEST_URL\"}"

  sleep 2
  req "Player state (playing)" GET  "/player/state"
  req "Pause"                POST "/player/pause"
  sleep 1
  req "Player state (paused)"  GET  "/player/state"
  req "Resume"               POST "/player/resume"
  sleep 1

  info "Adding to queue then skip"
  req "Add to queue"         POST "/queue/add"      "{\"youtube_url\":\"$TEST_URL\"}"
  req "Next song"            POST "/queue/next"
  sleep 1
  req "Stop"                 POST "/player/stop"
  req "Stop MPV process"     POST "/player/mpv/stop"
  req "State after stop"     GET  "/player/state"
fi

# ────────────────────────────────────────────────────────────
#  GROUP: tiktok
# ────────────────────────────────────────────────────────────
if should_run tiktok; then
  header "TIKTOK SIMULATE"
  req "TikTok status"        GET  "/tiktok/status"

  QUERY_ENC=$(python3 -c "import urllib.parse; print(urllib.parse.quote('#req never gonna give you up'))")
  req "Simulate #req"        POST "/tiktok/simulate?user=penonton1&comment=$QUERY_ENC"

  sleep 3  # wait for yt-dlp search

  SKIP_ENC=$(python3 -c "import urllib.parse; print(urllib.parse.quote('#skip'))")
  req "Simulate #skip (1)"   POST "/tiktok/simulate?user=penonton2&comment=$SKIP_ENC"
  req "Simulate #skip (2)"   POST "/tiktok/simulate?user=penonton3&comment=$SKIP_ENC"

  QUEUE_ENC=$(python3 -c "import urllib.parse; print(urllib.parse.quote('#queue'))")
  req "Simulate #queue"      POST "/tiktok/simulate?user=penonton4&comment=$QUEUE_ENC"

  req "TikTok status after"  GET  "/tiktok/status"
fi

# ────────────────────────────────────────────────────────────
#  GROUP: overlay
# ────────────────────────────────────────────────────────────
if should_run overlay; then
  header "OBS OVERLAY CONFIG"
  req "Get overlay config"   GET  "/overlay/config"
  req "Overlay state"        GET  "/overlay/state"

  info "Toggle hide request feed..."
  req "Hide request_feed"    PUT  "/overlay/config"  '{"show_request_feed":false}'
  sleep 1
  req "Show request_feed"    PUT  "/overlay/config"  '{"show_request_feed":true}'

  info "Change accent color..."
  req "Change accent orange" PUT  "/overlay/config"  '{"accent_color":"#f97316"}'
  req "Change accent blue"   PUT  "/overlay/config"  '{"accent_color":"#3b82f6","accent_color2":"#8b5cf6"}'
  sleep 1
  req "Reset accent orange"  PUT  "/overlay/config"  '{"accent_color":"#f97316","accent_color2":"#a855f7"}'

  info "Move queue panel to left..."
  req "Queue panel left"     PUT  "/overlay/config"  '{"position_queue":"left"}'
  sleep 1
  req "Queue panel right"    PUT  "/overlay/config"  '{"position_queue":"right"}'

  info "Toggle panels..."
  req "Hide skip vote"       PUT  "/overlay/config"  '{"show_skip_vote":false}'
  req "Hide thumbnail"       PUT  "/overlay/config"  '{"show_thumbnail":false}'
  req "Restore all"          PUT  "/overlay/config"  '{"show_skip_vote":true,"show_thumbnail":true}'
fi

# ── Summary ────────────────────────────────────────────────
echo -e "\n${BOLD}─────────────── Result ───────────────${NC}"
echo -e "  ${GREEN}PASS${NC} : $PASS"
echo -e "  ${RED}FAIL${NC} : $FAIL"
[[ $SKIP -gt 0 ]] && echo -e "  ${YELLOW}SKIP${NC} : $SKIP"
echo ""
[[ $FAIL -eq 0 ]] && echo -e "${GREEN}All tests passed!${NC}" || echo -e "${RED}Some tests failed.${NC}"
echo ""
