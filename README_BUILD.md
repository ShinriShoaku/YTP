# YTPlayer – Build Instructions

## Source structure (before build)

```
yt-player/
├── main.py                 ← patched standalone version
├── config.json
├── queue.json              ← auto-created on first run
├── requirements.txt
├── ytplayer.spec           ← PyInstaller spec
├── build.sh                ← Linux build script
├── build.bat               ← Windows build script
├── obs_overlay.html
├── obs_nowplaying.html
├── obs_queue.html
├── obs_commands.html
├── obs_subtitle.html
├── obs_requests.html
├── assets/                 ← optional icons / images
└── mpv/
    ├── mpv.exe             ← Windows: put mpv.exe here before building
    └── mpv                 ← Linux:   not needed (uses system mpv)
```

---

## Linux build

```bash
# 1. Install system mpv (if not already installed)
sudo apt install mpv      # Debian / Ubuntu
# or
sudo dnf install mpv      # Fedora
# or
sudo pacman -S mpv        # Arch

# 2. Build
chmod +x build.sh
./build.sh
```

**Output:**
```
dist/YTPlayer/
├── ytplayer          ← run this
├── config.json
├── queue.json
├── mpv/              ← optional local mpv override
└── overlays/
    └── *.html
```

---

## Windows build

1. Download **mpv.exe** from https://mpv.io/installation/ (select the Windows build).  
   Place it at `mpv\mpv.exe` **before** running the build script.

2. Double-click **`build.bat`** (or run from a Command Prompt).

**Output:**
```
dist\YTPlayer\
├── YTPlayer.exe      ← run this
├── config.json
├── queue.json
├── mpv\
│   └── mpv.exe
└── overlays\
    └── *.html
```

---

## Running the app

Start the exe — it opens a console window showing the server URL:

```
Web UI  : http://localhost:8000/player
API docs: http://localhost:8000/docs
OBS     : http://localhost:8000/obs
```

Then add the OBS Browser Sources:

| Panel         | URL                                      |
|---------------|------------------------------------------|
| Now Playing   | http://localhost:8000/obs/nowplaying     |
| Queue         | http://localhost:8000/obs/queue          |
| Commands      | http://localhost:8000/obs/commands       |
| Subtitle      | http://localhost:8000/obs/subtitle       |
| Requests      | http://localhost:8000/obs/requests       |
| All-in-one    | http://localhost:8000/obs                |

---

## Custom port

Set the `PORT` environment variable before launching:

```bash
# Linux
PORT=9000 ./ytplayer

# Windows (cmd)
set PORT=9000 && YTPlayer.exe
```

---

## mpv detection order

1. `mpv/mpv` (or `mpv/mpv.exe`) — local subfolder next to the exe  
2. `mpv` on system `PATH` (Linux default)  
3. `ffplay` on system `PATH` (fallback)

On Linux the system-installed mpv is used automatically, so the `mpv/` folder can stay empty unless you want to pin a specific version.
