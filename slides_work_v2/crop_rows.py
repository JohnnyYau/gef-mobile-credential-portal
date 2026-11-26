# -*- coding: utf-8 -*-
"""Two overlapping high-magnification crops around the P14 roster row."""
from PIL import Image

SRC = r"C:\Users\johnn\Downloads\WhatsApp Image 2026-11-13 at 21.19.50.jpeg"
OUT_A = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\slides_work_v2\row-p14-a.png"
OUT_B = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\slides_work_v2\row-p14-b.png"

im = Image.open(SRC)
w, h = im.size

for out, y0, y1 in ((OUT_A, 292, 320), (OUT_B, 306, 334)):
    crop = im.crop((0, max(y0, 0), w, min(y1, h)))
    crop = crop.resize((crop.width * 6, crop.height * 6), Image.LANCZOS)
    crop.save(out)
    print("saved", out, crop.size)
    print("  content y:", y0, "-", y1)
