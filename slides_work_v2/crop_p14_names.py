# -*- coding: utf-8 -*-
"""High-magnification crop of the P14 member-name column."""
from PIL import Image

SRC = r"C:\Users\johnn\Downloads\WhatsApp Image 2026-11-13 at 21.19.50.jpeg"
OUT = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\slides_work_v2\roster-p14-names-8x.png"

im = Image.open(SRC)
w, h = im.size
row_h = h / 22.0

# P14 is the 14th row (index 13). Names column starts after the project-title column.
y0 = int(row_h * 13) - 2
y1 = int(row_h * 14) + 3
x0 = int(w * 0.40)
x1 = w
crop = im.crop((x0, max(y0, 0), x1, min(y1, h)))
crop = crop.resize((crop.width * 8, crop.height * 8), Image.LANCZOS)
crop.save(OUT)
print("saved", OUT, crop.size)
