"""Generate the two QR codes for the A0 poster.

Left code opens the demo video (stable YouTube link); right code opens the
source repository. Both encode plain https URLs, so they keep working after
the manuscript is printed — that is the whole point of not using the
trycloudflare address, which dies when the laptop sleeps.
"""

from pathlib import Path

import qrcode

HERE = Path(__file__).resolve().parent
OUT = HERE / "poster_assets"
OUT.mkdir(exist_ok=True)

TARGETS = {
    "qr-youtube.png": "https://youtu.be/nVgevH43FYA",
    "qr-github.png": "https://github.com/JohnnyYau/gef-mobile-credential-portal",
}

INK = "#1a1813"
PAPER = "#f7f4ec"

for name, url in TARGETS.items():
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=20,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color=INK, back_color=PAPER)
    path = OUT / name
    img.save(path)
    print(f"{name}  {img.size[0]}x{img.size[1]}  {url}")
