# -*- mode: python ; coding: utf-8 -*-
# ytplayer.spec  –  PyInstaller build spec
# Works on both Linux and Windows.

import sys, os

IS_WINDOWS = sys.platform == "win32"
EXE_NAME   = "YTPlayer" if IS_WINDOWS else "ytplayer"

block_cipher = None

# ── Collect all hidden imports yt-dlp / TikTokLive need ───────
hidden = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "starlette",
    "starlette.middleware",
    "starlette.routing",
    "anyio",
    "anyio._backends._asyncio",
    "yt_dlp",
    "yt_dlp.extractor",
    "yt_dlp.postprocessor",
    "websockets",
    "httpx",
    "httpcore",
]

# TikTokLive is optional – add if present
try:
    import TikTokLive  # noqa: F401
    hidden += ["TikTokLive", "TikTokLive.client", "TikTokLive.events"]
except ImportError:
    pass

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],          # HTML / JSON are NOT bundled – they live next to the exe
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "pandas", "PIL", "tkinter",
        "PyQt5", "wx", "gi",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # console window shows server log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # add icon= "assets/icon.ico" here if you have one
)
