#!/usr/bin/env python3
"""
YouTube Audio Player API
FastAPI + yt-dlp | File-based Queue + Server-Side Audio (mpv IPC)
v4.0 – TikTok Live + Windows mpv support + OBS Overlay SSE
"""

import sys
import asyncio
import threading
from queue import Queue as SyncQueue
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import yt_dlp
import subprocess
import json
import uuid
import random
import urllib.request
import urllib.parse
import socket
import os
import time
import traceback
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────
#  Platform Detection
# ─────────────────────────────────────────────────────────────

IS_WINDOWS = sys.platform == "win32"

# ─────────────────────────────────────────────────────────────
#  Base directory – works for both dev and PyInstaller builds
# ─────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    # Running as PyInstaller bundle – place config/html next to the exe
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────────────────────────────────────────
#  App Setup
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Single lifespan handler – replaces deprecated @app.on_event('startup')."""
    global _sse_loop, _server_player
    # ── startup ────────────────────────────────────────────────
    _sse_loop = asyncio.get_event_loop()

    found = _detect_player()
    if found:
        _server_player = found
        print(f"[Startup] Player found: {found}")
    else:
        print("[Startup] WARNING: mpv/ffplay not found. Place mpv.exe in same folder as main.py")

    _start_tiktok_listener()
    yield
    # ── shutdown (nothing needed) ──────────────────────────────


app = FastAPI(
    title="YouTube Audio Player API",
    description="Stream YouTube audio via server-side mpv. Queue stored in queue.json.",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
#  Config Loading
# ─────────────────────────────────────────────────────────────

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

def _load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_config = _load_config()

def _get_commands() -> dict:
    """Returns command prefixes from config, with defaults."""
    cmds = _config.get("commands", {})
    return {
        "request": [c.lower() for c in cmds.get("request", ["#req", "#request", "#lagu", "#song"])],
        "skip":    [c.lower() for c in cmds.get("skip",    ["#skip", "#next", "#lewat"])],
        "stop":    [c.lower() for c in cmds.get("stop",    ["#stop"])],
        "queue":   [c.lower() for c in cmds.get("queue",   ["#queue", "#antrian", "#q"])],
    }

def _get_tiktok_username() -> str:
    """Return TikTok username stripped of any leading '@'."""
    raw = _config.get("tiktok_username", "")
    return raw.lstrip("@")   # TikTokLiveClient wants bare username, no @

def _get_settings() -> dict:
    return _config.get("settings", {
        "max_queue_per_user": 3,
        "enable_skip_vote": True,
        "skip_vote_threshold": 5,
    })

# ─────────────────────────────────────────────────────────────
#  Models
# ─────────────────────────────────────────────────────────────

class Song(BaseModel):
    id: str
    title: str
    youtube_url: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    channel: Optional[str] = None
    added_at: str
    requested_by: Optional[str] = None  # TikTok username

class AddToQueueRequest(BaseModel):
    youtube_url: str

class ReorderRequest(BaseModel):
    from_position: int
    to_position: int

class SwapRequest(BaseModel):
    position_a: int
    position_b: int

# ─────────────────────────────────────────────────────────────
#  File-based Queue State
# ─────────────────────────────────────────────────────────────

QUEUE_FILE = os.path.join(BASE_DIR, "queue.json")
_lock = threading.Lock()

current_song: Optional[Song] = None
current_song_start_time: float = 0.0
is_playing: bool = False
is_paused: bool = False
shuffle_mode: bool = False

skip_votes: set = set()   # set of user IDs who voted skip
_recent_requests: list = []  # last 20 TikTok requests for overlay
_subtitle_song_id: Optional[str] = None   # tracks which song subtitle thread is for

def _load_queue() -> List[dict]:
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_queue(q: List[dict]):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=2, ensure_ascii=False)

def _queue_snapshot():
    q = _load_queue()
    return [{"position": i, "song": s} for i, s in enumerate(q)]

def _queue_len() -> int:
    return len(_load_queue())

def _add_recent_request(entry: dict):
    """Keep last 20 TikTok requests for the overlay."""
    global _recent_requests
    _recent_requests.insert(0, entry)
    _recent_requests = _recent_requests[:20]

# ─────────────────────────────────────────────────────────────
#  MPV Detection (local mpv/ subfolder first, then system PATH)
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR   = BASE_DIR                                    # legacy alias kept for safety
OVERLAYS_DIR = os.path.join(BASE_DIR, "overlays")         # HTML overlays live here

def _find_local_player(name: str) -> Optional[str]:
    """Look for player executable in the same folder as this script."""
    candidates = [
        os.path.join(SCRIPT_DIR, name),
        os.path.join(SCRIPT_DIR, name + ".exe"),
        os.path.join(SCRIPT_DIR, "mpv", name),
        os.path.join(SCRIPT_DIR, "mpv", name + ".exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None

def _detect_player() -> Optional[str]:
    """Find mpv or ffplay. Checks local folder before PATH."""
    for name in ("mpv", "ffplay"):
        local = _find_local_player(name)
        if local:
            return local
        try:
            subprocess.run([name, "--version"], capture_output=True, timeout=3)
            return name
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return None

# ─────────────────────────────────────────────────────────────
#  Server-side audio player (mpv IPC – Windows & Unix)
# ─────────────────────────────────────────────────────────────

_mpv_proc: Optional[subprocess.Popen] = None
_server_player: Optional[str] = None
_player_killed: bool = False

# IPC paths differ by OS
if IS_WINDOWS:
    MPV_SOCKET     = r'\\.\pipe\ytapi-mpv'
    MPV_SOCKET_ARG = r'//./pipe/ytapi-mpv'
else:
    MPV_SOCKET     = "/tmp/ytapi-mpv.sock"
    MPV_SOCKET_ARG = MPV_SOCKET


def _mpv_send_unix(command: list, timeout: float = 2.0) -> Optional[dict]:
    if not os.path.exists(MPV_SOCKET):
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(MPV_SOCKET)
            msg = json.dumps({"command": command}) + "\n"
            sock.sendall(msg.encode())
            resp = b""
            while b"\n" not in resp:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp += chunk
            return json.loads(resp.decode().strip()) if resp else None
    except Exception as e:
        print(f"[MPV IPC Unix] {e}")
        return None


def _mpv_send_windows(command: list, timeout: float = 2.0) -> Optional[dict]:
    """Send command to mpv via Windows named pipe with thread timeout."""
    result: list = [None]

    def _do():
        try:
            with open(MPV_SOCKET, 'r+b', buffering=0) as f:
                msg = json.dumps({"command": command}).encode() + b'\n'
                f.write(msg)
                resp = f.read(4096)
                if resp:
                    # mpv may send multiple lines; grab first valid JSON
                    for line in resp.decode('utf-8', errors='ignore').splitlines():
                        line = line.strip()
                        if line:
                            try:
                                result[0] = json.loads(line)
                                break
                            except Exception:
                                pass
        except Exception as e:
            print(f"[MPV IPC Windows] {e}")

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0]


def _mpv_send(command: list, timeout: float = 2.0) -> Optional[dict]:
    if IS_WINDOWS:
        return _mpv_send_windows(command, timeout)
    return _mpv_send_unix(command, timeout)


def _kill_server_player():
    global _mpv_proc, _player_killed
    _player_killed = True
    if _mpv_proc and _mpv_proc.poll() is None:
        if _server_player and "mpv" in _server_player:
            _mpv_send(["quit"], timeout=1)
            time.sleep(0.3)
        if _mpv_proc.poll() is None:
            _mpv_proc.terminate()
            try:
                _mpv_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _mpv_proc.kill()
                _mpv_proc.wait()
    _mpv_proc = None
    if not IS_WINDOWS:
        try:
            if os.path.exists(MPV_SOCKET):
                os.remove(MPV_SOCKET)
        except Exception:
            pass


def _pause_server_audio():
    global is_paused
    if _server_player and "mpv" in _server_player and _mpv_proc and _mpv_proc.poll() is None:
        _mpv_send(["set_property", "pause", True])
        is_paused = True


def _resume_server_audio():
    global is_paused
    if _server_player and "mpv" in _server_player and _mpv_proc and _mpv_proc.poll() is None:
        _mpv_send(["set_property", "pause", False])
        is_paused = False


def _play_server_audio(youtube_url: str) -> bool:
    global _mpv_proc, _server_player, is_paused, _player_killed, current_song_start_time
    _kill_server_player()
    _player_killed = False
    is_paused = False

    if _server_player is None:
        _server_player = _detect_player()
    if _server_player is None:
        return False

    try:
        stream_url = _get_audio_stream_url(youtube_url)
        player_bin = _server_player  # may be a full path on Windows

        if "mpv" in os.path.basename(player_bin):
            cmd = [
                player_bin,
                "--no-video", "--really-quiet", "--no-terminal",
                f"--input-ipc-server={MPV_SOCKET_ARG}",
                stream_url,
            ]
        else:  # ffplay fallback
            cmd = [player_bin, "-nodisp", "-autoexit", "-loglevel", "quiet", stream_url]

        _mpv_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        current_song_start_time = time.time()
        # Auto-broadcast subtitles in background
        if current_song:
            _start_subtitle_broadcaster(current_song, current_song_start_time)
        return True
    except Exception as e:
        print(f"[SERVER PLAYER] Error starting player: {e}")
        return False

# ─────────────────────────────────────────────────────────────
#  SSE Infrastructure (for OBS Overlay)
# ─────────────────────────────────────────────────────────────

_sse_loop: Optional[asyncio.AbstractEventLoop] = None
_sse_queues: List[asyncio.Queue] = []
_sse_clients_lock = threading.Lock()


def _broadcast(event_type: str, data: dict):
    """
    Thread-safe broadcast to all connected SSE clients.
    Can be called from sync threads (TikTok listener, player watcher).
    """
    if _sse_loop is None:
        return
    msg = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _put_all():
        with _sse_clients_lock:
            for q in _sse_queues[:]:
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    pass

    _sse_loop.call_soon_threadsafe(_put_all)


def _broadcast_player_state():
    """Convenience: broadcast current player + queue state."""
    _broadcast("player_state", {
        "current_song": current_song.model_dump() if current_song else None,
        "is_playing": is_playing,
        "is_paused": is_paused,
        "queue_count": _queue_len(),
        "queue": [item["song"]["title"] for item in _queue_snapshot()[:5]],
    })

# ─────────────────────────────────────────────────────────────
#  TikTok Live Listener
# ─────────────────────────────────────────────────────────────

try:
    from TikTokLive import TikTokLiveClient
    from TikTokLive.events import ConnectEvent, CommentEvent, DisconnectEvent
    TIKTOK_AVAILABLE = True
except ImportError:
    TIKTOK_AVAILABLE = False
    print("[TikTok] TikTokLive library not installed.")
    print("[TikTok] Install with: pip install TikTokLive")

_tiktok_client = None
_tiktok_connected: bool = False
_tiktok_error: str = ""

# Per-user request count (reset on each song change)
_user_request_count: dict = {}


def _process_tiktok_comment(user_id: str, nickname: str, comment: str):
    """
    Parse and handle a TikTok comment. Called from async thread executor.
    """
    global skip_votes, _user_request_count

    comment = comment.strip()
    comment_lower = comment.lower()
    cmds = _get_commands()
    settings = _get_settings()

    # ── Skip command ──────────────────────────────────────────
    for prefix in cmds["skip"]:
        if comment_lower == prefix or comment_lower.startswith(prefix + " "):
            # Admin (tiktok_username in config) skips instantly, no vote needed
            admin_username = _get_tiktok_username()
            is_admin = admin_username and (
                user_id.lower() == admin_username.lower()
                or nickname.lower() == admin_username.lower()
            )

            if is_admin:
                print(f"[TikTok] Admin skip by @{nickname} – skipping instantly")
                _broadcast("skip_vote", {
                    "user": nickname,
                    "votes": settings.get("skip_vote_threshold", 5),
                    "threshold": settings.get("skip_vote_threshold", 5),
                    "admin": True,
                })
                _add_recent_request({"type": "skip", "user": nickname, "text": comment, "time": _now()})
                _do_skip(triggered_by=nickname)
                return

            skip_votes.add(user_id)
            threshold = settings.get("skip_vote_threshold", 5)
            vote_count = len(skip_votes)
            print(f"[TikTok] Skip vote from @{nickname} ({vote_count}/{threshold})")

            _broadcast("skip_vote", {
                "user": nickname,
                "votes": vote_count,
                "threshold": threshold,
            })
            _add_recent_request({"type": "skip", "user": nickname, "text": comment, "time": _now()})

            if vote_count >= threshold:
                _do_skip(triggered_by=nickname)
            return

    # ── Request command ───────────────────────────────────────
    for prefix in cmds["request"]:
        if comment_lower.startswith(prefix):
            query = comment[len(prefix):].strip()
            if not query:
                return
            max_per_user = settings.get("max_queue_per_user", 3)
            count = _user_request_count.get(user_id, 0)
            if count >= max_per_user:
                _broadcast("request_rejected", {
                    "user": nickname,
                    "reason": f"Max {max_per_user} requests per user",
                    "query": query,
                })
                return

            print(f"[TikTok] Request from @{nickname}: {query}")
            _add_recent_request({"type": "request", "user": nickname, "text": query, "status": "searching", "time": _now()})
            _broadcast("tiktok_request", {
                "user": nickname,
                "query": query,
                "status": "searching",
            })

            try:
                results = _search_youtube(query, limit=1)
                if not results:
                    _broadcast("tiktok_request", {"user": nickname, "query": query, "status": "not_found"})
                    if _recent_requests:
                        _recent_requests[0]["status"] = "not_found"
                    return
                top = results[0]
                info = _get_info(top["url"])
                song = _make_song(info, top["url"])
                song.requested_by = nickname
                _add_or_autoplay(song)
                _user_request_count[user_id] = count + 1
                if _recent_requests:
                    _recent_requests[0]["status"] = "queued"
                    _recent_requests[0]["song_title"] = song.title

                _broadcast("tiktok_request", {
                    "user": nickname,
                    "query": query,
                    "status": "queued",
                    "song_title": song.title,
                    "thumbnail": song.thumbnail,
                })
                _broadcast_player_state()
            except Exception as e:
                print(f"[TikTok] Request error: {e}")
                _broadcast("tiktok_request", {"user": nickname, "query": query, "status": "error", "error": str(e)})
            return

    # ── Queue info command ────────────────────────────────────
    for prefix in cmds["queue"]:
        if comment_lower == prefix:
            count = _queue_len()
            _broadcast("queue_info", {"user": nickname, "queue_count": count})
            return


def _do_skip(triggered_by: str = ""):
    """Internal skip: advance to next song."""
    global current_song, is_playing, is_paused, skip_votes, _user_request_count
    with _lock:
        q = _load_queue()
        if q:
            if shuffle_mode:
                idx = random.randint(0, len(q) - 1)
                song_dict = q.pop(idx)
            else:
                song_dict = q.pop(0)
            _save_queue(q)
            current_song = Song(**song_dict)
            is_playing = True
            is_paused = False
        else:
            current_song = None
            is_playing = False
            is_paused = False
    skip_votes = set()
    _user_request_count = {}
    if current_song:
        _play_server_audio(current_song.youtube_url)
    else:
        _kill_server_player()
    _broadcast("skip_executed", {"triggered_by": triggered_by})
    _broadcast_player_state()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _start_tiktok_listener():
    """Start TikTok Live listener in a background thread with its own event loop.
    Auto-reconnects every 30 s if the connection drops.
    """
    if not TIKTOK_AVAILABLE:
        return

    username = _get_tiktok_username()
    if not username:
        print("[TikTok] No username set in config.json – listener not started.")
        return

    def _run():
        global _tiktok_client, _tiktok_connected, _tiktok_error

        while True:                          # ← reconnect loop
            print(f"[TikTok] Connecting to @{username}…")
            try:
                # Re-create client each attempt so event handlers are fresh
                client = TikTokLiveClient(unique_id=username)
                _tiktok_client = client

                @client.on(ConnectEvent)
                async def on_connect(event: ConnectEvent):
                    global _tiktok_connected
                    _tiktok_connected = True
                    _tiktok_error = ""
                    print(f"[TikTok] ✓ Connected to @{username}")
                    _broadcast("tiktok_status", {"connected": True, "username": username})

                @client.on(DisconnectEvent)
                async def on_disconnect(event: DisconnectEvent):
                    global _tiktok_connected
                    _tiktok_connected = False
                    print(f"[TikTok] Disconnected from @{username}")
                    _broadcast("tiktok_status", {"connected": False, "username": username})

                @client.on(CommentEvent)
                async def on_comment(event: CommentEvent):
                    uid  = str(event.user.unique_id)
                    nick = event.user.nickname or uid
                    text = event.comment or ""
                    # run_in_executor so yt-dlp search doesn't block TikTok event loop
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None, _process_tiktok_comment, uid, nick, text
                    )

                # client.run() is the correct blocking call for TikTokLive v6+
                # It manages its own event loop internally.
                # Do NOT use loop.run_until_complete(client.start()) – that races
                # with the library's own loop and exits silently.
                client.run()

                # If we get here the library returned normally (user went offline)
                print(f"[TikTok] Session ended for @{username} (user not live?)")

            except Exception as e:
                _tiktok_error = str(e)
                print(f"[TikTok] Error ({type(e).__name__}): {e}")
                traceback.print_exc()          # full stack trace → no more silent fails
            finally:
                _tiktok_connected = False
                _broadcast("tiktok_status", {"connected": False, "username": username})

            print("[TikTok] Reconnecting in 30 s…")
            time.sleep(30)

    t = threading.Thread(target=_run, daemon=True, name="tiktok-listener")
    t.start()
    print(f"[TikTok] Listener thread started for @{username}")


# ─────────────────────────────────────────────────────────────
#  Player State & Watcher
# ─────────────────────────────────────────────────────────────

@app.get("/player/state", tags=["player"])
def player_state():
    running = _mpv_proc is not None and _mpv_proc.poll() is None
    elapsed_ms = 0
    if running and is_playing and not is_paused and current_song_start_time > 0:
        elapsed_ms = int((time.time() - current_song_start_time) * 1000)
    return {
        "is_playing": is_playing,
        "is_paused": is_paused,
        "server_audio_running": running,
        "shuffle_mode": shuffle_mode,
        "current_song": current_song.model_dump() if current_song else None,
        "elapsed_ms": elapsed_ms,
        "queue_count": _queue_len(),
        "queue": _queue_snapshot(),
    }


def _mpv_watcher():
    """Background thread: auto-advance when mpv exits naturally."""
    global current_song, is_playing, is_paused, _player_killed, _user_request_count, skip_votes
    while True:
        time.sleep(3)
        if _mpv_proc is None:
            if _player_killed:
                _player_killed = False
            continue
        if _mpv_proc.poll() is None:
            continue
        if _player_killed:
            _player_killed = False
            continue
        # mpv died naturally → advance
        skip_votes = set()
        _user_request_count = {}
        with _lock:
            q = _load_queue()
            if q:
                if shuffle_mode:
                    idx = random.randint(0, len(q) - 1)
                    song_dict = q.pop(idx)
                else:
                    song_dict = q.pop(0)
                _save_queue(q)
                current_song = Song(**song_dict)
                is_playing = True
                is_paused = False
                next_url = current_song.youtube_url
            else:
                current_song = None
                is_playing = False
                is_paused = False
                next_url = None
        if next_url:
            _play_server_audio(next_url)
        _broadcast_player_state()


threading.Thread(target=_mpv_watcher, daemon=True, name="mpv-watcher").start()

# ─────────────────────────────────────────────────────────────
#  yt-dlp Helpers
# ─────────────────────────────────────────────────────────────

def _ydl_quiet():
    return {"quiet": True, "no_warnings": True}

def _search_youtube(query: str, limit: int = 10) -> list:
    opts = {**_ydl_quiet(), "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        raw = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    results = []
    for e in raw.get("entries", []):
        if not e:
            continue
        vid_id = e.get("id", "")
        results.append({
            "id": vid_id,
            "title": e.get("title", "Unknown"),
            "url": f"https://www.youtube.com/watch?v={vid_id}",
            "thumbnail": e.get("thumbnail", f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"),
            "duration": e.get("duration"),
            "channel": e.get("channel") or e.get("uploader", ""),
            "view_count": e.get("view_count"),
        })
    return results

def _get_info(url: str) -> dict:
    with yt_dlp.YoutubeDL({**_ydl_quiet(), "skip_download": True}) as ydl:
        return ydl.extract_info(url, download=False)

def _get_audio_stream_url(url: str) -> str:
    opts = {**_ydl_quiet(), "format": "bestaudio[ext=m4a]/bestaudio/best"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    for fmt in info.get("formats", []):
        if fmt.get("acodec") not in (None, "none") and fmt.get("vcodec") in (None, "none"):
            return fmt["url"]
    return info.get("url") or info.get("webpage_url") or url

def _ms_to_timecode(ms: int) -> str:
    s, rem = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{rem:03d}"

def _parse_json3_subtitle(raw: dict) -> list:
    events = []
    for evt in raw.get("events", []):
        segs = evt.get("segs")
        if not segs:
            continue
        text = "".join(seg.get("utf8", "") for seg in segs).strip()
        if text:
            events.append({
                "start_ms": evt.get("tStartMs", 0),
                "duration_ms": evt.get("dDurationMs", 0),
                "start_time": _ms_to_timecode(evt.get("tStartMs", 0)),
                "text": text,
            })
    return events

def _fetch_subtitle_events_for_url(url: str) -> list:
    """Fetch subtitle events via yt-dlp. Prefers id (Indonesian), then en."""
    try:
        opts = {
            **_ydl_quiet(),
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "json3",
            "subtitleslangs": ["all"],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        sub_map: dict = {}
        for lang_code, entries in (info.get("subtitles") or {}).items():
            for entry in entries:
                if entry.get("ext") == "json3":
                    sub_map[lang_code] = {"type": "manual", "url": entry["url"]}
                    break
        for lang_code, entries in (info.get("automatic_captions") or {}).items():
            if lang_code not in sub_map:
                for entry in entries:
                    if entry.get("ext") == "json3":
                        sub_map[lang_code] = {"type": "auto", "url": entry["url"]}
                        break

        if not sub_map:
            print("[Subtitle] No subtitles/captions available.")
            return []

        # Language priority: id → en → whatever is first
        used_lang: Optional[str] = None
        for pref in ["id", "en", "en-US", "en-GB", "en-orig"]:
            if pref in sub_map:
                used_lang = pref
                break
        if not used_lang:
            for pref in ["id", "en"]:
                matches = [k for k in sub_map if k.startswith(pref)]
                if matches:
                    used_lang = matches[0]
                    break
        if not used_lang:
            used_lang = next(iter(sub_map))

        sub_url = sub_map[used_lang]["url"]
        with urllib.request.urlopen(sub_url, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        events = _parse_json3_subtitle(raw)
        print(f"[Subtitle] Loaded {len(events)} events in '{used_lang}'")
        return events
    except Exception as e:
        print(f"[Subtitle] Fetch error: {e}")
        return []


def _start_subtitle_broadcaster(song: "Song", song_start_time: float):
    """Spawn a daemon thread that broadcasts subtitle SSE events timed to playback."""
    global _subtitle_song_id
    song_id = song.id
    _subtitle_song_id = song_id

    def _run():
        events = _fetch_subtitle_events_for_url(song.youtube_url)
        if not events:
            return

        for evt in events:
            if _subtitle_song_id != song_id:
                return  # song changed – abort

            fire_at = song_start_time + (evt["start_ms"] / 1000.0)
            now = time.time()
            delay = fire_at - now

            if delay < -1.5:
                continue  # already past – skip

            if delay > 0:
                # Sleep in small chunks so song-change cancels quickly
                slept = 0.0
                while slept < delay:
                    if _subtitle_song_id != song_id:
                        return
                    chunk = min(0.15, delay - slept)
                    time.sleep(chunk)
                    slept += chunk

            if _subtitle_song_id != song_id:
                return

            _broadcast("subtitle", {
                "text": evt["text"],
                "duration_ms": min(int(evt["duration_ms"]) + 400, 7000),
            })

        # All events done – clear subtitle
        if _subtitle_song_id == song_id:
            time.sleep(1)
            _broadcast("subtitle_clear", {})

    threading.Thread(target=_run, daemon=True, name=f"sub-{song_id[:8]}").start()

def _make_song(info: dict, url: str) -> Song:
    return Song(
        id=str(uuid.uuid4()),
        title=info.get("title", "Unknown"),
        youtube_url=url,
        thumbnail=info.get("thumbnail"),
        duration=info.get("duration"),
        channel=info.get("channel") or info.get("uploader"),
        added_at=datetime.now(timezone.utc).isoformat(),
    )

def _add_or_autoplay(song: Song) -> dict:
    global current_song, is_playing, is_paused
    autoplay_url = None
    result = {}
    with _lock:
        if not is_playing and current_song is None:
            current_song = song
            is_playing = True
            is_paused = False
            autoplay_url = song.youtube_url
            result = {
                "auto_played": True,
                "message": "Auto-playing – player was idle",
                "song": song.model_dump(),
                "queue_count": _queue_len(),
                "server_audio": False,
            }
        else:
            q = _load_queue()
            if shuffle_mode and q:
                pos = random.randint(0, len(q))
                q.insert(pos, song.model_dump())
                queue_position = pos
            else:
                q.append(song.model_dump())
                queue_position = len(q) - 1
            _save_queue(q)
            result = {
                "auto_played": False,
                "message": "Added to queue",
                "song": song.model_dump(),
                "queue_position": queue_position,
                "queue_count": len(q),
            }
    if autoplay_url:
        server_playing = _play_server_audio(autoplay_url)
        result["server_audio"] = server_playing
    return result

# ─────────────────────────────────────────────────────────────
#  Root
# ─────────────────────────────────────────────────────────────

@app.get("/", tags=["info"])
def root():
    return {
        "app": "YouTube Audio Player API",
        "version": "4.0.0",
        "docs": "/docs",
        "player": "/player",
        "obs_overlay": "/obs",
        "platform": "windows" if IS_WINDOWS else sys.platform,
        "player_found": _detect_player() or "not found",
        "tiktok_available": TIKTOK_AVAILABLE,
        "tiktok_connected": _tiktok_connected,
        "tiktok_username": _get_tiktok_username(),
    }

# ─────────────────────────────────────────────────────────────
#  Search
# ─────────────────────────────────────────────────────────────

@app.get("/search", tags=["youtube"])
def search(q: str = Query(...), limit: int = Query(10, ge=1, le=20)):
    try:
        results = _search_youtube(q, limit)
        return {"query": q, "count": len(results), "results": results}
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))

@app.post("/search/add-top", tags=["youtube"])
def search_add_top(q: str = Query(...)):
    try:
        results = _search_youtube(q, limit=1)
    except Exception as exc:
        raise HTTPException(500, detail=f"Search error: {exc}")
    if not results:
        raise HTTPException(404, detail="No results found")
    top = results[0]
    try:
        info = _get_info(top["url"])
    except Exception as exc:
        raise HTTPException(500, detail=f"Info fetch error: {exc}")
    song = _make_song(info, top["url"])
    result = _add_or_autoplay(song)
    result["search_query"] = q
    result["top_result"] = top
    _broadcast_player_state()
    return result

@app.get("/info", tags=["youtube"])
def video_info(url: str = Query(...)):
    try:
        info = _get_info(url)
        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "channel": info.get("channel") or info.get("uploader"),
            "view_count": info.get("view_count"),
            "description": (info.get("description") or "")[:500],
            "url": url,
        }
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))

# ─────────────────────────────────────────────────────────────
#  Subtitles
# ─────────────────────────────────────────────────────────────

@app.get("/subtitles", tags=["youtube"])
def get_subtitles(url: str = Query(...), lang: str = Query("en")):
    try:
        opts = {
            **_ydl_quiet(),
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "json3",
            "subtitleslangs": ["all"],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        sub_map = {}
        for lang_code, entries in (info.get("subtitles") or {}).items():
            for entry in entries:
                if entry.get("ext") == "json3":
                    sub_map[lang_code] = {"type": "manual", "url": entry["url"]}
                    break
        for lang_code, entries in (info.get("automatic_captions") or {}).items():
            if lang_code not in sub_map:
                for entry in entries:
                    if entry.get("ext") == "json3":
                        sub_map[lang_code] = {"type": "auto", "url": entry["url"]}
                        break
        available = list(sub_map.keys())
        used_lang = None
        if lang in sub_map:
            used_lang = lang
        else:
            prefix_matches = [k for k in sub_map if k.startswith(lang + "-") or k.startswith(lang + ".")]
            if prefix_matches:
                used_lang = prefix_matches[0]
            elif available:
                used_lang = available[0]
        result = {
            "url": url, "title": info.get("title"),
            "available_languages": available,
            "requested_language": lang,
            "used_language": used_lang,
            "subtitles": {},
        }
        if used_lang:
            sub_url = sub_map[used_lang]["url"]
            with urllib.request.urlopen(sub_url) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            events = _parse_json3_subtitle(raw)
            result["subtitles"] = {
                "type": sub_map[used_lang]["type"],
                "language": used_lang,
                "event_count": len(events),
                "events": events,
            }
        return result
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))

@app.get("/subtitles/list", tags=["youtube"])
def list_subtitles_current():
    if current_song is None:
        raise HTTPException(404, detail="Nothing is currently playing")
    url = current_song.youtube_url
    try:
        opts = {
            **_ydl_quiet(),
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "json3",
            "subtitleslangs": ["all"],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        sub_map: dict = {}
        for lang_code, entries in (info.get("subtitles") or {}).items():
            for entry in entries:
                if entry.get("ext") == "json3":
                    sub_map[lang_code] = "manual"
                    break
        for lang_code, entries in (info.get("automatic_captions") or {}).items():
            if lang_code not in sub_map:
                for entry in entries:
                    if entry.get("ext") == "json3":
                        sub_map[lang_code] = "auto"
                        break
        available = list(sub_map.keys())
        return {
            "url": url,
            "title": current_song.title,
            "song_id": current_song.id,
            "available_languages": available,
            "languages_detail": [{"code": k, "type": v} for k, v in sub_map.items()],
            "count": len(available),
        }
    except Exception as exc:
        return {
            "url": url,
            "title": current_song.title if current_song else None,
            "song_id": current_song.id if current_song else None,
            "available_languages": [],
            "languages_detail": [],
            "count": 0,
            "error": str(exc),
        }

@app.get("/subtitles/current", tags=["youtube"])
def get_subtitles_current(lang: str = Query("en")):
    if current_song is None:
        raise HTTPException(404, detail="Nothing is currently playing")
    url = current_song.youtube_url
    try:
        opts = {
            **_ydl_quiet(),
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "json3",
            "subtitleslangs": ["all"],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        sub_map = {}
        for lang_code, entries in (info.get("subtitles") or {}).items():
            for entry in entries:
                if entry.get("ext") == "json3":
                    sub_map[lang_code] = {"type": "manual", "url": entry["url"]}
                    break
        for lang_code, entries in (info.get("automatic_captions") or {}).items():
            if lang_code not in sub_map:
                for entry in entries:
                    if entry.get("ext") == "json3":
                        sub_map[lang_code] = {"type": "auto", "url": entry["url"]}
                        break
        available = list(sub_map.keys())
        used_lang = None
        if lang in sub_map:
            used_lang = lang
        else:
            prefix_matches = [k for k in sub_map if k.startswith(lang + "-") or k.startswith(lang + ".")]
            if prefix_matches:
                used_lang = prefix_matches[0]
            elif available:
                used_lang = available[0]
        result = {
            "url": url,
            "title": info.get("title"),
            "song_id": current_song.id,
            "available_languages": available,
            "requested_language": lang,
            "used_language": used_lang,
            "subtitles": {},
        }
        if not used_lang:
            return result
        sub_url = sub_map[used_lang]["url"]
        with urllib.request.urlopen(sub_url) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        events = _parse_json3_subtitle(raw)
        result["subtitles"] = {
            "type": sub_map[used_lang]["type"],
            "language": used_lang,
            "event_count": len(events),
            "events": events,
        }
        return result
    except HTTPException:
        raise
    except Exception as exc:
        return {
            "url": url,
            "title": current_song.title if current_song else None,
            "song_id": current_song.id if current_song else None,
            "available_languages": [],
            "requested_language": lang,
            "used_language": None,
            "subtitles": {},
            "error": str(exc),
        }

# ─────────────────────────────────────────────────────────────
#  Audio
# ─────────────────────────────────────────────────────────────

@app.get("/audio/url", tags=["audio"])
def audio_url(url: str = Query(...)):
    try:
        info = _get_info(url)
        stream_url = _get_audio_stream_url(url)
        return {
            "title": info.get("title"),
            "audio_url": stream_url,
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "note": "URL expires – re-fetch if playback fails",
        }
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))

@app.get("/audio/stream", tags=["audio"])
def stream_audio(url: str = Query(...), bitrate: str = Query("192k")):
    try:
        stream_url = _get_audio_stream_url(url)
    except Exception as exc:
        raise HTTPException(500, detail=f"yt-dlp error: {exc}")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
        "-fflags", "+nobuffer", "-thread_queue_size", "512",
        "-i", stream_url, "-vn", "-c:a", "libmp3lame", "-b:a", bitrate,
        "-bufsize", "64k", "-f", "mp3", "pipe:1",
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    except FileNotFoundError:
        raise HTTPException(500, detail="ffmpeg not found")
    def _generate():
        try:
            first = proc.stdout.read(8_192)
            if first:
                yield first
            while True:
                chunk = proc.stdout.read(16_384)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    return StreamingResponse(
        _generate(), media_type="audio/mpeg",
        headers={
            "Content-Disposition": 'inline; filename="audio.mp3"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache", "Expires": "0",
            "Accept-Ranges": "none",
        },
    )

@app.get("/audio/curl-cmd", tags=["audio"])
def curl_play_cmd(url: str = Query(...)):
    encoded = urllib.parse.quote(url)
    base = "http://localhost:8000"
    return {
        "mpv_direct": f"mpv '{base}/audio/stream?url={encoded}&bitrate=192k'",
        "ffplay_direct": f"ffplay -nodisp -autoexit '{base}/audio/stream?url={encoded}&bitrate=192k'",
        "stream_url": f"{base}/audio/stream?url={encoded}&bitrate=192k",
    }

# ─────────────────────────────────────────────────────────────
#  Queue Management
# ─────────────────────────────────────────────────────────────

@app.get("/queue", tags=["queue"])
def get_queue():
    return {
        "is_playing": is_playing,
        "is_paused": is_paused,
        "shuffle_mode": shuffle_mode,
        "current_song": current_song.model_dump() if current_song else None,
        "queue_count": _queue_len(),
        "queue": _queue_snapshot(),
    }

@app.post("/queue/add", tags=["queue"])
def add_to_queue(body: AddToQueueRequest):
    try:
        info = _get_info(body.youtube_url)
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))
    song = _make_song(info, body.youtube_url)
    result = _add_or_autoplay(song)
    _broadcast_player_state()
    return result

@app.post("/queue/shuffle", tags=["queue"])
def toggle_shuffle():
    global shuffle_mode
    with _lock:
        shuffle_mode = not shuffle_mode
        q = _load_queue()
        if shuffle_mode and q:
            random.shuffle(q)
            _save_queue(q)
    _broadcast_player_state()
    return {
        "shuffle_mode": shuffle_mode,
        "message": f"Shuffle {'ON – queue shuffled' if shuffle_mode else 'OFF'}",
        "queue_count": _queue_len(),
        "queue": _queue_snapshot(),
    }

@app.delete("/queue/{position}", tags=["queue"])
def remove_from_queue(position: int):
    with _lock:
        q = _load_queue()
        if position < 0 or position >= len(q):
            raise HTTPException(404, detail=f"Position {position} not found (size: {len(q)})")
        removed = Song(**q.pop(position))
        _save_queue(q)
    _broadcast_player_state()
    return {"message": "Removed", "removed_song": removed.model_dump(), "queue_count": len(q)}

@app.put("/queue/reorder", tags=["queue"])
def reorder_queue(body: ReorderRequest):
    with _lock:
        q = _load_queue()
        n = len(q)
        if not (0 <= body.from_position < n):
            raise HTTPException(400, detail="from_position out of range")
        if not (0 <= body.to_position < n):
            raise HTTPException(400, detail="to_position out of range")
        song = q.pop(body.from_position)
        q.insert(body.to_position, song)
        _save_queue(q)
    _broadcast_player_state()
    return {"message": f"Moved {body.from_position} → {body.to_position}", "queue": _queue_snapshot()}

@app.put("/queue/swap", tags=["queue"])
def swap_queue(body: SwapRequest):
    with _lock:
        q = _load_queue()
        n = len(q)
        if not (0 <= body.position_a < n and 0 <= body.position_b < n):
            raise HTTPException(400, detail="Position out of range")
        q[body.position_a], q[body.position_b] = q[body.position_b], q[body.position_a]
        _save_queue(q)
    _broadcast_player_state()
    return {"message": f"Swapped {body.position_a} ↔ {body.position_b}", "queue": _queue_snapshot()}

@app.post("/queue/next", tags=["queue"])
def next_song():
    _do_skip(triggered_by="api")
    return {
        "message": "Playing next" if current_song else "Queue is empty",
        "current_song": current_song.model_dump() if current_song else None,
        "is_playing": is_playing,
        "queue_remaining": _queue_len(),
    }

@app.post("/queue/clear", tags=["queue"])
def clear_queue():
    with _lock:
        _save_queue([])
    _broadcast_player_state()
    return {"message": "Queue cleared", "queue_count": 0}

# ─────────────────────────────────────────────────────────────
#  Player Endpoints
# ─────────────────────────────────────────────────────────────

@app.post("/player/play", tags=["player"])
def play_now(body: AddToQueueRequest):
    global current_song, is_playing, is_paused
    try:
        info = _get_info(body.youtube_url)
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))
    song = _make_song(info, body.youtube_url)
    with _lock:
        current_song = song
        is_playing = True
        is_paused = False
    server_playing = _play_server_audio(body.youtube_url)
    _broadcast_player_state()
    return {"message": "Playing now", "song": song.model_dump(), "server_audio": server_playing}

@app.post("/player/pause", tags=["player"])
def pause_player():
    _pause_server_audio()
    _broadcast_player_state()
    return {"message": "Paused", "is_paused": is_paused}

@app.post("/player/resume", tags=["player"])
def resume_player():
    _resume_server_audio()
    _broadcast_player_state()
    return {"message": "Resumed", "is_paused": is_paused}

@app.post("/player/song-ended", tags=["player"])
def song_ended():
    global current_song, is_playing, is_paused
    with _lock:
        finished = current_song
        q = _load_queue()
        if q:
            if shuffle_mode:
                idx = random.randint(0, len(q) - 1)
                song_dict = q.pop(idx)
            else:
                song_dict = q.pop(0)
            _save_queue(q)
            current_song = Song(**song_dict)
            is_playing = True
            is_paused = False
        else:
            current_song = None
            is_playing = False
            is_paused = False
    server_playing = False
    if current_song:
        server_playing = _play_server_audio(current_song.youtube_url)
    _broadcast_player_state()
    return {
        "auto_cleared": True,
        "finished_song": finished.model_dump() if finished else None,
        "next_song": current_song.model_dump() if current_song else None,
        "queue_remaining": _queue_len(),
        "is_playing": is_playing,
        "is_paused": is_paused,
        "server_audio": server_playing,
    }

@app.post("/player/stop", tags=["player"])
def stop_player():
    global current_song, is_playing, is_paused
    with _lock:
        current_song = None
        is_playing = False
        is_paused = False
    _kill_server_player()
    _broadcast("player_stopped", {})
    _broadcast_player_state()
    return {"message": "Player stopped"}

@app.get("/player/mpv/status", tags=["player"])
def mpv_status():
    running = _mpv_proc is not None and _mpv_proc.poll() is None
    paused = False
    if running and _server_player and "mpv" in _server_player:
        resp = _mpv_send(["get_property", "pause"])
        if resp and "data" in resp:
            paused = resp["data"]
    return {
        "server_player": _server_player or _detect_player() or "none",
        "is_running": running,
        "is_paused": paused,
        "current_song": current_song.model_dump() if current_song else None,
        "platform": "windows" if IS_WINDOWS else sys.platform,
        "mpv_socket": MPV_SOCKET_ARG,
    }

@app.post("/player/mpv/stop", tags=["player"])
def mpv_stop():
    _kill_server_player()
    return {"message": "Server audio stopped"}

# ─────────────────────────────────────────────────────────────
#  TikTok Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/tiktok/status", tags=["tiktok"])
def tiktok_status():
    return {
        "library_installed": TIKTOK_AVAILABLE,
        "connected": _tiktok_connected,
        "username": _get_tiktok_username(),
        "error": _tiktok_error,
        "commands": _get_commands(),
        "settings": _get_settings(),
        "recent_requests": _recent_requests[:10],
        "skip_votes": len(skip_votes),
        "skip_threshold": _get_settings().get("skip_vote_threshold", 5),
    }

@app.post("/tiktok/simulate", tags=["tiktok"])
def tiktok_simulate(user: str = Query("testuser"), comment: str = Query(...)):
    """Test TikTok comment handling without a live stream."""
    _process_tiktok_comment(user, user, comment)
    return {"message": "Comment simulated", "user": user, "comment": comment}

@app.post("/tiktok/reconnect", tags=["tiktok"])
def tiktok_reconnect():
    """Restart the TikTok listener thread."""
    _start_tiktok_listener()
    return {"message": "TikTok listener restarted", "username": _get_tiktok_username()}

# ─────────────────────────────────────────────────────────────
#  OBS Overlay SSE
# ─────────────────────────────────────────────────────────────

@app.get("/overlay/events", tags=["overlay"])
async def overlay_events(request: Request):
    """Server-Sent Events endpoint for OBS overlay."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    with _sse_clients_lock:
        _sse_queues.append(q)

    async def generate():
        try:
            # Send initial state immediately
            init_data = {
                "current_song": current_song.model_dump() if current_song else None,
                "is_playing": is_playing,
                "is_paused": is_paused,
                "queue_count": _queue_len(),
                "queue": [item["song"]["title"] for item in _queue_snapshot()[:5]],
                "tiktok_connected": _tiktok_connected,
                "recent_requests": _recent_requests[:10],
                "commands": _get_commands(),
            }
            yield f"event: init\ndata: {json.dumps(init_data, ensure_ascii=False)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            with _sse_clients_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )

@app.get("/overlay/state", tags=["overlay"])
def overlay_state():
    """Snapshot of all overlay data (poll fallback)."""
    return {
        "current_song": current_song.model_dump() if current_song else None,
        "is_playing": is_playing,
        "is_paused": is_paused,
        "queue_count": _queue_len(),
        "queue": [item["song"] for item in _queue_snapshot()[:5]],
        "tiktok_connected": _tiktok_connected,
        "recent_requests": _recent_requests[:10],
        "skip_votes": len(skip_votes),
        "skip_threshold": _get_settings().get("skip_vote_threshold", 5),
        "elapsed_ms": int((time.time() - current_song_start_time) * 1000) if is_playing and not is_paused and current_song_start_time > 0 else 0,
    }

# ─────────────────────────────────────────────────────────────
#  HTML Remote UI  (original, unchanged)
# ─────────────────────────────────────────────────────────────

@app.get("/player", response_class=HTMLResponse, tags=["player"])
def player_ui():
    html = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YT Audio Remote</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#111827;color:#e5e7eb;min-height:100vh}
.app{max-width:820px;margin:0 auto;padding:24px 16px}
h1{text-align:center;color:#f97316;margin-bottom:24px;font-size:1.6rem;letter-spacing:.5px}
.search-row{display:flex;gap:8px;margin-bottom:20px}
.search-row input{flex:1;padding:10px 14px;border-radius:8px;border:1px solid #374151;background:#1f2937;color:#e5e7eb;font-size:15px;outline:none}
.search-row input:focus{border-color:#f97316}
.btn{padding:10px 18px;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;transition:all .15s}
.btn:hover{opacity:.85}
.btn-primary{background:#f97316;color:#fff}
.btn-secondary{background:#374151;color:#e5e7eb}
.btn-danger{background:#ef4444;color:#fff}
.btn-sm{padding:4px 10px;font-size:12px;border-radius:5px}
.btn-shuffle{background:#374151;color:#9ca3af;border:1px solid #374151}
.btn-shuffle.on{background:#6d28d9;color:#fff;border-color:#7c3aed;box-shadow:0 0 8px #7c3aed55}
.results-section{margin-bottom:20px}
.result-card{display:flex;gap:12px;align-items:center;padding:10px 12px;background:#1f2937;border-radius:8px;margin-bottom:8px;border:1px solid #374151}
.result-card:hover{border-color:#f97316;background:#1a2332}
.thumb{width:88px;height:50px;object-fit:cover;border-radius:5px;flex-shrink:0;background:#374151}
.result-meta{flex:1;min-width:0}
.result-title{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.result-sub{font-size:11px;color:#9ca3af;margin-top:2px}
.result-btns{display:flex;gap:6px;flex-shrink:0}
.player-card{background:#1f2937;border-radius:12px;padding:20px;margin-bottom:20px;border:1px solid #374151}
.player-header{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#f97316;margin-bottom:8px}
.now-title{font-size:15px;font-weight:600;margin-bottom:14px;min-height:20px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.controls{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:14px}
.controls .btn{font-size:16px;padding:12px 22px;border-radius:10px}
.player-status{text-align:center;margin-top:10px;font-size:12px;color:#9ca3af;min-height:18px}
.queue-card{background:#1f2937;border-radius:12px;padding:20px;border:1px solid #374151}
.queue-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.queue-title{font-size:14px;font-weight:700}
.queue-actions{display:flex;gap:6px;align-items:center}
.queue-empty{text-align:center;padding:20px;color:#6b7280;font-size:13px}
.q-item{display:flex;align-items:center;gap:8px;padding:8px;background:#111827;border-radius:6px;margin-bottom:6px;border:1px solid #1f2937}
.q-pos{width:22px;text-align:center;font-size:12px;color:#6b7280;flex-shrink:0}
.q-info{flex:1;min-width:0;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.q-dur{font-size:11px;color:#9ca3af;flex-shrink:0}
.q-btns{display:flex;gap:4px;flex-shrink:0}
.icon-btn{background:#374151;color:#e5e7eb;border:none;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:13px}
.icon-btn:hover{background:#4b5563}
.icon-btn.red{background:#7f1d1d;color:#fca5a5}
.icon-btn.red:hover{background:#ef4444;color:#fff}
.status{font-size:11px;color:#6b7280;text-align:center;margin-top:6px}
.spin{display:inline-block;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="app">
  <h1>🎵 YT Audio Remote</h1>
  <div class="search-row">
    <input id="q" type="text" placeholder="Search YouTube music…" onkeydown="if(event.key==='Enter') doSearch()">
    <button class="btn btn-primary" onclick="doSearch()">Search</button>
  </div>
  <div id="results" class="results-section"></div>
  <div class="player-card">
    <div class="player-header">▶ Now Playing</div>
    <div id="nowTitle" class="now-title">— nothing playing —</div>
    <div class="controls">
      <button class="btn btn-primary" id="playBtn" onclick="togglePlay()">▶ Play</button>
      <button class="btn btn-secondary" onclick="stopPlayer()">⏹ Stop</button>
      <button class="btn btn-secondary" onclick="nextSong()">⏭ Next</button>
    </div>
    <div class="player-status" id="playerStatus">Idle</div>
  </div>
  <div class="queue-card">
    <div class="queue-header">
      <div class="queue-title">📋 Queue &nbsp;<span id="qCount" style="color:#f97316">0</span></div>
      <div class="queue-actions">
        <button id="shuffleBtn" class="btn btn-shuffle btn-sm" onclick="toggleShuffle()">🔀 Shuffle</button>
        <button class="btn btn-danger btn-sm" onclick="clearQueue()">Clear All</button>
      </div>
    </div>
    <div id="qList"><div class="queue-empty">Queue is empty</div></div>
  </div>
  <div class="status" id="status">Ready</div>
</div>
<script>
const API='';
let queueData=[], shuffleOn=false, lastServerRunning=false;

async function doSearch(){
  const q=document.getElementById('q').value.trim(); if(!q) return;
  setStatus('Searching…');
  document.getElementById('results').innerHTML='<div style="text-align:center;padding:20px;color:#9ca3af"><span class="spin">⏳</span> Searching…</div>';
  try{ const data=await api('GET',`/search?q=${enc(q)}&limit=10`); renderResults(data.results||[]); setStatus(`Found ${data.count} results`); }
  catch(e){ document.getElementById('results').innerHTML=`<div style="color:#ef4444;padding:8px">Error: ${e.message}</div>`; }
}
function renderResults(items){
  if(!items.length){ document.getElementById('results').innerHTML='<div style="color:#9ca3af;text-align:center;padding:10px">No results</div>'; return; }
  document.getElementById('results').innerHTML=items.map(it=>`
    <div class="result-card">
      <img class="thumb" src="${it.thumbnail||''}" onerror="this.style.background='#374151';this.removeAttribute('src')">
      <div class="result-meta">
        <div class="result-title" title="${esc(it.title)}">${esc(it.title)}</div>
        <div class="result-sub">${esc(it.channel||'')}${it.duration?' · '+fmt(it.duration):''}</div>
      </div>
      <div class="result-btns">
        <button class="btn btn-primary btn-sm" onclick="playNow('${esc(it.url)}','${esc(it.title).replace(/'/g,"\\'")}')">▶ Play</button>
        <button class="btn btn-secondary btn-sm" onclick="addToQueue('${esc(it.url)}','${esc(it.title).replace(/'/g,"\\'")}')">+ Queue</button>
      </div>
    </div>`).join('');
}

async function syncPlayerState(){
  try{
    const data=await api('GET','/player/state');
    document.getElementById('qCount').textContent=data.queue_count;
    queueData=data.queue||[]; shuffleOn=data.shuffle_mode||false;
    _updateShuffleBtn(); renderQueue();
    const nowTitle=document.getElementById('nowTitle'), playBtn=document.getElementById('playBtn'), pStatus=document.getElementById('playerStatus');
    if(data.current_song){
      nowTitle.textContent=data.current_song.title;
      if(data.is_playing&&!data.is_paused){ playBtn.textContent='⏸ Pause'; pStatus.textContent='▶ Playing'; }
      else if(data.is_paused){ playBtn.textContent='▶ Resume'; pStatus.textContent='⏸ Paused'; }
      else { playBtn.textContent='▶ Play'; pStatus.textContent='⏹ Stopped'; }
    } else { nowTitle.textContent='— nothing playing —'; playBtn.textContent='▶ Play'; pStatus.textContent='Idle'; }
    lastServerRunning=data.server_audio_running;
  }catch(_){}
}

async function togglePlay(){
  const state=await api('GET','/player/state');
  if(state.is_playing&&!state.is_paused){ await api('POST','/player/pause'); }
  else if(state.is_paused){ await api('POST','/player/resume'); }
  else {
    if(state.current_song){ await api('POST','/player/play',{youtube_url:state.current_song.youtube_url}); }
    else if(state.queue_count>0){ await api('POST','/queue/next'); }
    else { setStatus('Queue is empty'); return; }
  }
  await syncPlayerState();
}
async function stopPlayer(){ await api('POST','/player/stop'); await syncPlayerState(); }
async function nextSong(){ await api('POST','/queue/next'); await syncPlayerState(); }
async function playNow(url,title){
  setStatus('Loading…'); document.getElementById('nowTitle').textContent=title+' – loading…';
  try{ await api('POST','/player/play',{youtube_url:url}); }catch(_){}
  await syncPlayerState();
}
async function addToQueue(url,title){
  setStatus('Adding…');
  try{ const data=await api('POST','/queue/add',{youtube_url:url}); await syncPlayerState(); if(data.auto_played) setStatus('Auto-playing: '+data.song.title); else setStatus(`Queued #${data.queue_position+1}: ${data.song.title}`); }
  catch(e){ setStatus('Error: '+e.message); }
}

async function toggleShuffle(){
  try{ const data=await api('POST','/queue/shuffle'); shuffleOn=data.shuffle_mode; _updateShuffleBtn(); queueData=data.queue||[]; document.getElementById('qCount').textContent=data.queue_count; renderQueue(); setStatus(data.message); }
  catch(e){ setStatus('Error: '+e.message); }
}
function _updateShuffleBtn(){ const btn=document.getElementById('shuffleBtn'); btn.classList.toggle('on',shuffleOn); btn.textContent=shuffleOn?'🔀 Shuffle ON':'🔀 Shuffle'; }

async function refreshQueue(){ await syncPlayerState(); }
function renderQueue(){
  if(!queueData.length){ document.getElementById('qList').innerHTML='<div class="queue-empty">Queue is empty</div>'; return; }
  document.getElementById('qList').innerHTML=queueData.map((item,i)=>{
    const s=item.song;
    return `<div class="q-item"><div class="q-pos">${i+1}</div><div class="q-info" title="${esc(s.title)}">${esc(s.title)}</div><div class="q-dur">${s.duration?fmt(s.duration):''}</div><div class="q-btns"><button class="icon-btn" onclick="moveQ(${i},${i-1})" ${i===0?'disabled':''}>↑</button><button class="icon-btn" onclick="moveQ(${i},${i+1})" ${i===queueData.length-1?'disabled':''}>↓</button><button class="icon-btn" onclick="playNow('${s.youtube_url}','${esc(s.title).replace(/'/g,"\\'")}')">▶</button><button class="icon-btn red" onclick="removeQ(${i})">✕</button></div></div>`;
  }).join('');
}
async function moveQ(from,to){ if(to<0||to>=queueData.length) return; await api('PUT','/queue/reorder',{from_position:from,to_position:to}); await refreshQueue(); }
async function removeQ(pos){ await api('DELETE',`/queue/${pos}`); await refreshQueue(); }
async function clearQueue(){ await api('POST','/queue/clear'); await syncPlayerState(); setStatus('Queue cleared'); }

async function api(method,path,body){
  const opts={method,headers:{'Content-Type':'application/json'}};
  if(body) opts.body=JSON.stringify(body);
  const r=await fetch(API+path,opts);
  if(!r.ok){ const t=await r.text(); throw new Error(t); }
  return r.json();
}
const enc=encodeURIComponent;
const esc=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmt=s=>{ const m=Math.floor(s/60),sc=s%60; return `${m}:${String(sc).padStart(2,'0')}`; };
const setStatus=t=>document.getElementById('status').textContent=t;

syncPlayerState();
setInterval(syncPlayerState,3000);
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ─────────────────────────────────────────────────────────────
#  Overlay Config endpoint  (read & hot-reload from config.json)
# ─────────────────────────────────────────────────────────────

_DEFAULT_OVERLAY_CONFIG = {
    # ── Panels visibility ─────────────────────────────────────
    "show_now_playing":    True,   # bottom bar
    "show_queue":          True,   # right panel: queue list
    "show_request_feed":   True,   # right panel: TikTok request log
    "show_commands_hint":  True,   # left panel: command cheat-sheet
    "show_skip_vote":      True,   # skip vote dots in bottom bar
    "show_next_up":        True,   # "Next Up" toast when song changes
    "show_progress_bar":   True,   # progress bar at bottom of now-playing bar
    "show_thumbnail":      True,   # album art thumbnail
    "show_requester":      True,   # "@user requested" badge
    "show_channel":        True,   # artist/channel name
    "show_tiktok_dot":     True,   # live dot indicator
    "show_subtitle":       True,   # subtitle/lyrics panel (auto-fetched from YouTube captions)

    # ── Limits ────────────────────────────────────────────────
    "max_queue_items":     6,      # how many queue rows to show
    "max_request_items":   8,      # how many request feed rows to show

    # ── Style ─────────────────────────────────────────────────
    "accent_color":       "#f97316",   # primary accent (orange)
    "accent_color2":      "#a855f7",   # secondary accent (purple)
    "font_size_title":     20,          # px, now-playing title
    "subtitle_font_size":  28,          # px, subtitle text
    "opacity_panels":      0.82,        # 0.0–1.0 background opacity of panels
    "position_queue":     "right",      # "right" | "left"
    "position_commands":  "left",       # "right" | "left" | "hidden"
}

@app.get("/overlay/config", tags=["overlay"])
def overlay_config():
    """Returns the merged overlay display config (defaults + config.json overrides)."""
    cfg = _load_config()
    user_overlay = cfg.get("overlay", {})
    merged = {**_DEFAULT_OVERLAY_CONFIG, **user_overlay}
    return merged

@app.put("/overlay/config", tags=["overlay"])
def save_overlay_config(body: dict):
    """
    Saves overlay config to config.json and broadcasts update to all OBS clients.
    Only keys that exist in the default schema are accepted.
    """
    cfg = _load_config()
    current = cfg.get("overlay", {})
    # Only allow known keys
    for k, v in body.items():
        if k in _DEFAULT_OVERLAY_CONFIG:
            current[k] = v
    cfg["overlay"] = current
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise HTTPException(500, detail=f"Could not save config: {e}")
    merged = {**_DEFAULT_OVERLAY_CONFIG, **current}
    _broadcast("overlay_config", merged)
    return {"message": "Config saved", "overlay": merged}


# ─────────────────────────────────────────────────────────────
#  OBS Overlay HTML
# ─────────────────────────────────────────────────────────────

@app.get("/obs", response_class=HTMLResponse, tags=["overlay"])
def obs_overlay():
    """OBS Browser Source overlay – combined full overlay."""
    path = os.path.join(OVERLAYS_DIR, "obs_overlay.html")
    if not os.path.exists(path):
        raise HTTPException(404, detail="obs_overlay.html not found in overlays/ directory")
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

def _serve_html(filename: str) -> HTMLResponse:
    path = os.path.join(OVERLAYS_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, detail=f"{filename} not found in overlays/ directory")
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/obs/nowplaying", response_class=HTMLResponse, tags=["overlay"])
def obs_nowplaying():
    """Modular: now-playing bar only."""
    return _serve_html("obs_nowplaying.html")

@app.get("/obs/queue", response_class=HTMLResponse, tags=["overlay"])
def obs_queue():
    """Modular: queue panel only."""
    return _serve_html("obs_queue.html")

@app.get("/obs/commands", response_class=HTMLResponse, tags=["overlay"])
def obs_commands():
    """Modular: commands hint panel only."""
    return _serve_html("obs_commands.html")

@app.get("/obs/subtitle", response_class=HTMLResponse, tags=["overlay"])
def obs_subtitle():
    """Modular: subtitle/lyrics display only."""
    return _serve_html("obs_subtitle.html")

@app.get("/obs/requests", response_class=HTMLResponse, tags=["overlay"])
def obs_requests():
    """Modular: TikTok request feed only."""
    return _serve_html("obs_requests.html")


# (startup logic moved to lifespan handler at top of file)

# ─────────────────────────────────────────────────────────────
#  Standalone entry-point  (python main.py  OR  ./ytplayer)
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))

    print("=" * 56)
    print("  YTPlayer  –  YouTube Audio Player + OBS Overlay")
    print("=" * 56)
    print(f"  Base dir  : {BASE_DIR}")
    print(f"  Overlays  : {OVERLAYS_DIR}")
    print(f"  Config    : {CONFIG_FILE}")
    print(f"  Queue     : {QUEUE_FILE}")
    print(f"  Platform  : {'Windows' if IS_WINDOWS else sys.platform}")
    print(f"  MPV       : {_detect_player() or '⚠  not found – place mpv in mpv/ folder'}")
    print(f"  Web UI    : http://localhost:{port}/player")
    print(f"  API docs  : http://localhost:{port}/docs")
    print(f"  OBS (all) : http://localhost:{port}/obs")
    print("=" * 56)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",   # keep console clean; errors still shown
    )
