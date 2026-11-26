# -*- coding: utf-8 -*-
"""Crop and upscale the P13-P15 rows of the course roster screenshot for exact name reading."""
from PIL import Image

SRC = r"C:\Users\johnn\Downloads\WhatsApp Image 2026-11-13 at 21.19.50.jpeg"
OUT1 = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\slides_work_v2\roster-p13-p15.png"
OUT2 = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\slides_work_v2\roster-p14-zoom.png"

im = Image.open(SRC)
print("size:", im.size, "mode:", im.mode)
w, h = im.size

# rows: 21 projects spread over roughly y=8..460 -> ~21.5 px per row
row_h = h / 22.0
def band(rows, top_pad=0, bottom_pad=0):
    y0 = int(row_h * rows[0]) - top_pad
    y1 = int(row_h * rows[-1] + row_h) + bottom_pad
    return im.crop((0, max(y0, 0), w, min(y1, h)))

b1 = band([12, 13, 14, 15])           # P13..P15 (1-based index 12..14 -> rows 12,13,14)
b1 = b1.resize((b1.width * 3, b1.height * 3), Image.LANCZOS)
b1.save(OUT1)
print("saved", OUT1, b1.size)

b2 = band([13, 14])                   # P14 + P15
b2 = b2.resize((b2.width * 4, b2.height * 4), Image.LANCZOS)
b2.save(OUT2)
print("saved", OUT2, b2.size)
