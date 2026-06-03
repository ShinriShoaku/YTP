#!/usr/bin/env bash
# build.sh – Build YTPlayer standalone for Linux
# Usage:  chmod +x build.sh && ./build.sh
set -e

# === 🛠️ SET VERSI APLIKASI DI SINI ===
APP_VERSION="v3.1.0-tester"
DIST_NAME="YTPlayer-${APP_VERSION}"
DIST_DIR="dist/${DIST_NAME}"

echo "============================================"
echo "  YTPlayer Linux Build (${APP_VERSION})"
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
rm -rf build/ "dist/YTPlayer*" # Membersihkan folder dist versi lama juga

# ── 5. PyInstaller ───────────────────────────────────────────
echo "[INFO] Running PyInstaller..."
pyinstaller ytplayer.spec --noconfirm --clean

# ── 6. Assemble final folder ──────────────────────────────────
echo "[INFO] Assembling output..."
mkdir -p "${DIST_DIR}/overlays"
mkdir -p "${DIST_DIR}/mpv"
mkdir -p "${DIST_DIR}/assets"

# Copy the compiled binary (PyInstaller default output biasanya di dist/ytplayer)
cp "dist/ytplayer" "${DIST_DIR}/ytplayer"
chmod +x "${DIST_DIR}/ytplayer"

# [BONUS] Tanam file versi ke dalam folder rilis
echo "${APP_VERSION}" > "${DIST_DIR}/version.txt"
echo "  + version.txt (${APP_VERSION})"

# Copy overlay HTML files
for f in obs_overlay.html obs_nowplaying.html obs_queue.html \
          obs_commands.html obs_subtitle.html obs_requests.html; do
    [ -f "$f" ] && cp "$f" "${DIST_DIR}/overlays/" && echo "  + overlays/$f"
done

# Copy main files langsung ke root folder dist
for f in player.html \
         badwords.txt \
         config.json; do
     [ -f "$f" ] && cp "$f" "${DIST_DIR}/" && echo "  + $f"
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

# ── 7. Auto-Packaging (Biar siap upload ke GitHub Release) ────
echo ""
echo "[INFO] Compressing build into tar.gz..."
cd dist
tar -czf "${DIST_NAME}-Linux.tar.gz" "${DIST_NAME}"
cd ..
echo "  + dist/${DIST_NAME}-Linux.tar.gz"

echo ""
echo "============================================"
echo "  Build complete!"
echo "  Folder Output: ${DIST_DIR}/"
echo "  File Archive:  dist/${DIST_NAME}-Linux.tar.gz"
echo "  Run:           ./${DIST_DIR}/ytplayer"
echo "============================================"