"""build_demo_video.py — assemble the demo video from the live screenshots in
docs/ (Week 3 deliverable, extended with the extras).

Renders two title cards with PIL, then stitches one 10s segment per screenshot
(ken-burns zoom, caption, fade in/out) and concatenates them.

Usage (from the portal root):
    python3 scripts/build_demo_video.py
Requires: ffmpeg on PATH, Pillow.
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
WORK = ROOT / "scripts" / ".video-tmp"
OUT = ROOT / "demo.mp4"

W, H = 1280, 720
FPS = 25
SEG_SECONDS = 10
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

SEGMENTS = [
    ("title.png", ""),
    ("screenshot-verify.png", "1 · Upload a diploma → six checks → VALID"),
    ("screenshot-tampered.png", "2 · Tampered document → INVALID (hash mismatch)"),
    ("screenshot-chat.png", "3 · Ask the AI → answers with sources"),
    ("screenshot-revoked.png", "4 · Revoke → REVOKED, append-only"),
    ("screenshot-qr.png", "5 · QR code → scan straight to a verdict"),
    ("screenshot-issue.png", "6 · Issue → QR + verifiable PDF + email"),
    ("screenshot-log.png", "7 · Public log + anomaly watch"),
    ("screenshot-student.png", "8 · Student self-service"),
    ("screenshot-signers.png", "9 · Multi-signer admin"),
    ("outro.png", ""),
]


def gradient_bg():
    img = Image.new("RGB", (W, H))
    top, bottom = (11, 61, 46), (6, 36, 28)
    for y in range(H):
        t = y / (H - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        ImageDraw.Draw(img).line([(0, y), (W, y)], fill=color)
    return img


def center_text(draw, y, text, font, fill=(255, 255, 255)):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((W - tw) / 2 - bbox[0], y), text, font=font, fill=fill)


def make_title(path, title, subtitle, footer):
    img = gradient_bg()
    draw = ImageDraw.Draw(img)
    f_title = ImageFont.truetype(FONT_BOLD, 66)
    f_sub = ImageFont.truetype(FONT_REG, 30)
    f_footer = ImageFont.truetype(FONT_REG, 24)
    center_text(draw, 220, title, f_title)
    center_text(draw, 330, subtitle, f_sub, fill=(200, 228, 216))
    draw.line([(W / 2 - 120, 420), (W / 2 + 120, 420)], fill=(90, 160, 130), width=3)
    center_text(draw, 448, footer, f_footer, fill=(150, 190, 175))
    img.save(WORK / path)


def make_outro():
    img = gradient_bg()
    draw = ImageDraw.Draw(img)
    f_big = ImageFont.truetype(FONT_BOLD, 72)
    f_mid = ImageFont.truetype(FONT_REG, 34)
    f_small = ImageFont.truetype(FONT_REG, 26)
    center_text(draw, 200, "Ship it", f_big)
    center_text(draw, 320, "uvicorn app.main:app", f_mid, fill=(200, 228, 216))
    center_text(draw, 392, "Dockerfile · render.yaml · railway.toml", f_small,
                fill=(150, 190, 175))
    center_text(draw, 444, "README with screenshots + deploy steps", f_small,
                fill=(150, 190, 175))
    img.save(WORK / "outro.png")


def segment(source, caption, idx):
    out = WORK / f"seg{idx}.mp4"
    src = WORK / source if (WORK / source).exists() else DOCS / source
    vf = (
        "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,"
        f"zoompan=z='min(1.0+0.0012*on,1.12)':d={SEG_SECONDS * FPS}:"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720:fps=25"
    )
    if caption:
        safe = caption.replace(":", "\\:").replace("'", "\u2019")
        vf += (f",drawtext=text='{safe}':fontsize=26:fontcolor=white:"
               "x=40:y=36:box=1:boxcolor=black@0.55:boxborderw=12")
    vf += ",fade=t=in:st=0:d=0.5,fade=t=out:st={}:d=0.5".format(SEG_SECONDS - 0.5)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        # no -loop/-t: zoompan itself emits d frames (250 = 10s @ 25fps)
        "-filter_complex", vf,
        "-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22",
        str(out),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr.decode("utf-8", errors="replace"))
        raise
    return out


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    for f in WORK.glob("*"):
        f.unlink()
    make_title("title.png",
               "Credential Verification Portal",
               "Verify diplomas on the Gef26 credential chain — 60-second demo",
               "ML-DSA · SHA3-512 · MiniLM + FAISS chat · 33 tests green")
    make_outro()

    segs = [segment(src, cap, i) for i, (src, cap) in enumerate(SEGMENTS)]
    listfile = WORK / "list.txt"
    listfile.write_text("".join(f"file '{s.name}'\n" for s in segs))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(OUT)],
        check=True, capture_output=True,
    )
    print(f"OK -> {OUT} ({OUT.stat().st_size / 1e6:.1f} MB, "
          f"{SEG_SECONDS * len(segs)}s)")


if __name__ == "__main__":
    sys.exit(main())
