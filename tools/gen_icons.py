#!/usr/bin/env python3
"""Generate PWA/home-screen icons. Run once on Actions, commit the PNGs, delete this."""
from PIL import Image, ImageDraw

PAPER = (18, 16, 14)      # --paper
MARK = (201, 162, 39)     # --mark (gold)
UP = (91, 158, 122)       # --up (green)


def make(size, path, margin_frac=0.22):
    img = Image.new("RGB", (size, size), PAPER)
    d = ImageDraw.Draw(img)
    m = int(size * margin_frac)
    x0, y0, x1, y1 = m, m, size - m, size - m
    w = x1 - x0
    # a small rising line-chart, echoing the dashboard's own sparkline
    pts = [(x0, y1 - w * 0.15), (x0 + w * 0.32, y1 - w * 0.5),
           (x0 + w * 0.62, y1 - w * 0.32), (x1, y0)]
    d.line(pts, fill=UP, width=max(2, size // 40), joint="curve")
    r = max(3, size // 28)
    for px, py in pts:
        d.ellipse([px - r, py - r, px + r, py + r], fill=MARK)
    img.save(path)


make(180, "dashboard/icon-180.png")
make(192, "dashboard/icon-192.png")
make(512, "dashboard/icon-512.png", margin_frac=0.26)  # more margin: maskable safe zone
print("icons written")
