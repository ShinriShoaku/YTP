"""
make_icon.py – Generate assets/icon.ico for YTPlayer
Requires: Pillow  (pip install pillow)
Called automatically by build.bat / build.sh
"""
import os, sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("[icon] Pillow not installed – skipping icon generation.")
    sys.exit(0)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

SIZES = [256, 128, 64, 48, 32, 16]
frames = []

for size in SIZES:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    s   = size

    # ── Background circle (dark navy) ────────────────────────
    mg = max(1, s // 20)
    d.ellipse([mg, mg, s - mg - 1, s - mg - 1], fill=(10, 10, 24, 255))

    # ── Outer ring (orange) ───────────────────────────────────
    rw = max(1, s // 14)
    d.ellipse([mg, mg, s - mg - 1, s - mg - 1],
              outline=(249, 115, 22, 255), width=rw)

    # ── Inner ring (purple, slightly smaller) ─────────────────
    ig = mg + rw + max(1, s // 22)
    rw2 = max(1, s // 22)
    d.ellipse([ig, ig, s - ig - 1, s - ig - 1],
              outline=(168, 85, 247, 180), width=rw2)

    # ── Play triangle (centred, orange) ──────────────────────
    cx, cy = s / 2, s / 2
    r = s * 0.26
    pts = [
        (round(cx - r * 0.55), round(cy - r)),
        (round(cx - r * 0.55), round(cy + r)),
        (round(cx + r * 0.95), round(cy)),
    ]
    d.polygon(pts, fill=(249, 115, 22, 255))

    # ── Highlight on play triangle ────────────────────────────
    if size >= 32:
        hd = max(2, s // 18)
        d.ellipse([cx - hd, cy - r * 0.55 - hd,
                   cx + hd, cy - r * 0.55 + hd],
                  fill=(255, 210, 130, 180))

    frames.append(img)

frames[0].save(
    OUT,
    format="ICO",
    sizes=[(f.width, f.height) for f in frames],
    append_images=frames[1:],
)
print(f"[icon] Saved {OUT}  ({os.path.getsize(OUT):,} bytes,  {len(SIZES)} sizes)")
