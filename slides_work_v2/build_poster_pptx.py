r"""Assemble the A0 poster deck from the rendered page.

The poster is laid out in HTML (slides_work_v2/poster.html) and rendered twice:
3507 px wide for screen review, 4967 px wide (150 dpi at A0) for print. This
script puts the print render on a single 841 x 1189 mm slide, which is what the
brief asks for (A0, one page, PPT, two QR codes).

Why not native shapes in python-pptx? The layout depends on real screenshots
and CJK line breaking; a browser does both better than hand-placed boxes, and
the deck stays a faithful single page.

Re-rendering the input (run from slides_work_v2/):

    chrome --headless=new --hide-scrollbars --window-size=3507,4961 \
           --force-device-scale-factor=2 --virtual-time-budget=8000 \
           --screenshot=<abs>\poster-2x.png file:///<abs>/poster.html

Then downscale to 4967 x 7022 (exactly 150 dpi at A0) with LANCZOS and save it
as poster_assets/poster-a0-print.png. Do not just raise --window-size to A0
pixels: the page keeps its 3507 x 4961 CSS canvas and the extra room stays
blank, which is what produced an empty third of the first PDF attempt.
"""

from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

HERE = Path(__file__).resolve().parent
IMG = HERE / "poster_assets" / "poster-a0-print.png"
OUT = HERE.parent / "P14-A0-Poster.pptx"

MM = 36000  # EMU per millimetre (914400 EMU/inch, 25.4 mm/inch)
W_MM, H_MM = 841, 1189  # A0 portrait

if not IMG.exists():
    raise SystemExit(f"missing render: {IMG}")

prs = Presentation()
prs.slide_width = Emu(W_MM * MM)
prs.slide_height = Emu(H_MM * MM)

slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
slide.shapes.add_picture(
    str(IMG), 0, 0, width=prs.slide_width, height=prs.slide_height
)

slide.notes_slide.notes_text_frame.text = (
    "A0 poster, 841 x 1189 mm, single page. Two QR codes: demo video (YouTube) "
    "and source repository (GitHub). Source: slides_work_v2/poster.html, "
    "rendered at 150 dpi."
)

prs.save(OUT)
print(f"{OUT.name}  {OUT.stat().st_size / 1e6:.2f} MB  "
      f"{prs.slide_width / MM:.0f} x {prs.slide_height / MM:.0f} mm")
