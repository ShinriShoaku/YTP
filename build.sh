#!/usr/bin/env bash
# build.sh – Build YTPlayer standalone for Linux
# Usage:  chmod +x build.sh && ./build.sh
set -e

DIST_NAME="YTPlayer"
DIST_DIR="dist/${DIST_NAME}"

echo "============================================"
echo "  YTPlayer Linux Build"
echo "============================================"

# ── 1. Check Python ──────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found.  Install it first."
    exit 1
fi
PYTHON=python3

# ── 2. Virtual-env (optional but clean) ──────────────────────
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtualenv..."
    $PYTHON -m venv .venv
fi
source .venv/bin/activate
echo "[INFO] Using Python: $(python --version)"

# ── 3. Install / upgrade deps ────────────────────────────────
echo "[INFO] Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pyinstaller -q

# ── 4. Clean previous build ──────────────────────────────────
echo "[INFO] Cleaning previous build..."
rm -rf build/ "${DIST_DIR}"

# ── 5. PyInstaller ───────────────────────────────────────────
echo "[INFO] Running PyInstaller..."
pyinstaller ytplayer.spec --noconfirm --clean

# ── 6. Assemble final folder ──────────────────────────────────
echo "[INFO] Assembling output..."
mkdir -p "${DIST_DIR}/overlays"
mkdir -p "${DIST_DIR}/mpv"
mkdir -p "${DIST_DIR}/assets"

# Copy the compiled binary
cp "dist/ytplayer" "${DIST_DIR}/ytplayer"
chmod +x "${DIST_DIR}/ytplayer"

# Copy overlay HTML files
for f in obs_overlay.html obs_nowplaying.html obs_queue.html \
          obs_commands.html obs_subtitle.html obs_requests.html; do
    [ -f "$f" ] && cp "$f" "${DIST_DIR}/overlays/" && echo "  + overlays/$f"
done

# Copy config / queue stubs (don't overwrite if already exists in dist)
[ ! -f "${DIST_DIR}/config.json" ] && cp config.json "${DIST_DIR}/config.json"
[ ! -f "${DIST_DIR}/queue.json"  ] && echo "[]" > "${DIST_DIR}/queue.json"

# Copy assets folder if it exists
[ -d "assets" ] && cp -r assets/. "${DIST_DIR}/assets/"

# System mpv note
echo ""
echo "[NOTE] On Linux, mpv is loaded from your system PATH by default."
echo "       If you want to bundle a local mpv binary, copy it to:"
echo "       ${DIST_DIR}/mpv/mpv"

echo ""
echo "============================================"
echo "  Build complete!"
echo "  Output: ${DIST_DIR}/"
echo "  Run:    ./${DIST_DIR}/ytplayer"
echo "============================================"
