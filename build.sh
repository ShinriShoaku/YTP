#!/usr/bin/env bash
# build.sh – Build YTPlayer (one-dir mode) for Linux
# One-dir: ytplayer = launcher, libs in _internal/ → fewer AV false positives
set -e

EXE_NAME="ytplayer"
DIST_DIR="dist/YTPlayer"

echo "============================================"
echo "  YTPlayer Linux Build  [one-dir mode]"
echo "============================================"

# ── 1. Check Python ──────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Install it first."
    exit 1
fi
PYTHON=python3
echo "[INFO] Using $($PYTHON --version)"

# ── 2. Virtual-env ───────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtualenv..."
    $PYTHON -m venv .venv
fi
source .venv/bin/activate

# ── 3. Install deps ──────────────────────────────────────────
echo "[INFO] Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pyinstaller pillow -q

# ── 4. Generate icon ─────────────────────────────────────────
echo "[INFO] Generating icon..."
mkdir -p assets
python make_icon.py || echo "[WARN] Icon generation failed, continuing without icon."

# ── 5. Clean previous build ──────────────────────────────────
echo "[INFO] Cleaning previous build..."
rm -rf build/ "${DIST_DIR}"

# ── 6. PyInstaller (one-dir) ─────────────────────────────────
echo "[INFO] Running PyInstaller (one-dir mode)..."
pyinstaller ytplayer.spec --noconfirm --clean

# Verify
if [ ! -f "${DIST_DIR}/${EXE_NAME}" ]; then
    echo "[ERROR] ${DIST_DIR}/${EXE_NAME} not found after build!"
    exit 1
fi
chmod +x "${DIST_DIR}/${EXE_NAME}"
echo "[OK] ${EXE_NAME} built successfully."

# ── 7. Inject overlays, config, mpv ──────────────────────────
echo "[INFO] Adding overlays and config..."
mkdir -p "${DIST_DIR}/overlays"
mkdir -p "${DIST_DIR}/mpv"
mkdir -p "${DIST_DIR}/assets"

for f in obs_overlay obs_nowplaying obs_queue obs_commands obs_subtitle obs_requests; do
    if [ -f "${f}.html" ]; then
        cp "${f}.html" "${DIST_DIR}/overlays/${f}.html"
        echo "  + overlays/${f}.html"
    fi
done

[ ! -f "${DIST_DIR}/config.json" ] && cp config.json "${DIST_DIR}/config.json" && echo "  + config.json"
[ ! -f "${DIST_DIR}/queue.json"  ] && echo "[]" > "${DIST_DIR}/queue.json"    && echo "  + queue.json"
[ -d "assets" ] && cp -r assets/. "${DIST_DIR}/assets/"                        && echo "  + assets/"

# ── 8. Note on mpv ───────────────────────────────────────────
echo ""
echo "[NOTE] mpv loaded from system PATH on Linux."
echo "       To use local mpv, copy binary to: ${DIST_DIR}/mpv/mpv"

echo ""
echo "============================================"
echo "  Build complete!  [one-dir]"
echo ""
echo "  Output  : ${DIST_DIR}/"
echo "  Run     : ./${DIST_DIR}/${EXE_NAME}"
echo ""
echo "  Structure:"
echo "    ${EXE_NAME}          <- launcher"
echo "    _internal/       <- Python libs"
echo "    overlays/        <- OBS HTML files"
echo "    config.json"
echo "============================================"
