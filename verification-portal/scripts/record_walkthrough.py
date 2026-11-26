"""Record a captioned walkthrough of the portal, headless and at real speed.

record_stage.py films one page. This films a short session: the home page, a
valid credential, a revoked one, an issuance, then the four-step stage run — in
one browser tab, so the block heights in the footage belong to one session.

Captions are burned in, in Traditional Chinese, because this cut is meant to be
watched without narration: at a booth a visitor reads them, and a caption cannot
drift out of sync with the picture the way a voice-over can. Nothing points at
the tunnel URL — that address dies with the tunnel, and a video outlives it.

    python scripts/record_walkthrough.py --out ..\\demo-media\\GEF-mobile-walkthrough.mp4

Timing: frames carry their capture timestamps and are resampled onto a 10 fps
grid, so a slow frame never stretches the video and the page's own "14 ms"
receipts stay honest.
"""

import argparse
import asyncio
import base64
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import websockets
from PIL import Image, ImageDraw, ImageFont

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = "http://127.0.0.1:8013"
W, H = 1600, 900
FPS = 10

VALID = ("GFiY4d67yoi8X4wmwnL_8IX18_xo_F7HOQgWBdHZXubNTLhvVX_K1PCWuKZa8cntDWyq5Mn"
         "r7i8yvAopAjxrGQ")
REVOKED = ("8pgPh4z-x2UUzV_eJxU3Eac-n1zblwOoKalGg0Tvf8Hg-7Pj8Vo78QiRrSgahOSLNU0ISvu"
           "rUAwmFaYfGumMIQ")

CREAM = (247, 244, 236)
INK = (26, 24, 19)


class CDP:
    """One reader task, one pending-response table.

    Responses and events arrive on a single socket, so a naive "read until my id
    comes back" helper eats the other caller's replies and both hang. Two
    coroutines share this tab — the capture loop and the step driver — so the
    socket is demultiplexed by id here.
    """

    def __init__(self, ws):
        self.ws = ws
        self.pending = {}
        self.next_id = 0
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                fut = self.pending.pop(msg.get("id"), None)
                if fut is None or fut.done():
                    continue
                if "error" in msg:
                    fut.set_exception(RuntimeError(str(msg["error"])))
                else:
                    fut.set_result(msg.get("result", {}))
        finally:
            # a closed socket must not leave anyone waiting on a reply
            for fut in self.pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("devtools socket closed"))
            self.pending.clear()

    async def call(self, method, timeout=15, **params):
        self.next_id += 1
        mid = self.next_id
        fut = asyncio.get_running_loop().create_future()
        self.pending[mid] = fut
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        return await asyncio.wait_for(fut, timeout=timeout)

    async def js(self, expression):
        out = await self.call("Runtime.evaluate", expression=expression,
                              returnByValue=True, awaitPromise=True)
        return out.get("result", {}).get("value")


TYPE_JS = """
(async () => {
  const fill = async (id, text, ms) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.focus();
    for (const ch of text) {
      el.value += ch;
      await new Promise(r => setTimeout(r, ms));
    }
  };
  await fill('nameInput', 'CHAN TAI MAN', 55);
  await fill('sidInput', '22000777', 55);
  await fill('degreeInput', 'Bachelor of Engineering', 45);
  document.getElementById('honourInput').value = '1ST HON';
  document.getElementById('dateInput').value = '20261127';
  const tok = document.getElementById('tokenInput');
  if (tok) tok.value = 'demo-staff-token';
  return 'filled';
})()
"""

SCROLL = ("document.getElementById('result').scrollIntoView({block:'start'});"
          "window.scrollBy(0,-96)")

# caption, path, seconds on screen, [(delay from step start, expression)]
STEPS = [
    ("驗證者打開門戶：貼上憑證，或上傳證書 PDF", "/", 5.0, []),
    ("同一頁上逐項亮起：取回塊、驗簽、比對內容、查撤銷",
     f"/verify?hash={VALID}", 9.0, [(1.8, SCROLL)]),
    ("已註銷的樣本：結論是「已註銷」，原因寫在鏈上",
     f"/verify?hash={REVOKED}", 7.5, [(1.2, SCROLL)]),
    ("簽發方填表 → 簽名 → 上鏈；新的塊號就是回執",
     "/issue", 16.0, [(1.2, TYPE_JS), (8.6, "document.getElementById('issueBtn').click()"),
                     (12.0, SCROLL)]),
    ("現場演示走完四環節：簽發 → 驗證 → 註銷 → 再驗",
     "/showtime?auto=1&token=demo-staff-token", 23.0, []),
]

TITLE_SEC, OUTRO_SEC = 3.4, 4.0


async def drive(cdp: CDP, when: float, path: str, acts) -> None:
    loop = asyncio.get_running_loop()
    delay = when - loop.time()
    if delay > 0:
        await asyncio.sleep(delay)
    await cdp.call("Page.navigate", url=BASE + path)
    for _ in range(60):
        if await cdp.js("document.readyState") == "complete":
            break
        await asyncio.sleep(0.2)
    for after, expr in acts:
        wait = when + after - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            await cdp.js(expr)
        except RuntimeError as err:
            print(f"  action skipped: {err}", file=sys.stderr)


async def capture(frames: Path, marks: list) -> int:
    """Walk the step list, grabbing frames on the fly with timestamps."""
    port = free_port()
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        f"--remote-debugging-port={port}", f"--window-size={W},{H}",
        f"--user-data-dir={tempfile.mkdtemp(prefix='walk-')}",
        "--no-first-run", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        target = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as r:
                    pages = [t for t in json.load(r) if t["type"] == "page"]
                if pages:
                    target = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            await asyncio.sleep(0.25)
        if not target:
            raise RuntimeError("chrome did not expose a debug target")

        async with websockets.connect(target, max_size=64 * 1024 * 1024) as ws:
            cdp = CDP(ws)
            await cdp.call("Page.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride",
                           width=W, height=H, deviceScaleFactor=1, mobile=False)

            loop = asyncio.get_running_loop()
            start = loop.time()
            clock = 0.0
            drivers = []
            for cap, path, sec, acts in STEPS:
                drivers.append(asyncio.create_task(drive(cdp, start + clock, path, acts)))
                clock += sec

            deadline = start + clock
            n = 0
            while loop.time() < deadline:
                tick = loop.time()
                if n == 0 and tick - start > 8:
                    raise RuntimeError("no frame arrived in the first 8s; tab is not rendering")
                try:
                    shot = await cdp.call("Page.captureScreenshot", timeout=6,
                                          format="jpeg", quality=88, fromSurface=True)
                except (RuntimeError, asyncio.TimeoutError):
                    await asyncio.sleep(0.05)
                    continue
                n += 1
                (frames / f"{n:05d}.jpg").write_bytes(base64.b64decode(shot["data"]))
                marks.append(tick - start)
            for d in drivers:
                d.cancel()
            cdp.reader.cancel()
            print(f"captured {n} frames over {marks[-1]:.1f}s")
            return n
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(r"C:\Windows\Fonts\msjh.ttc", size)


def card(lines, path: Path) -> None:
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    total = sum(font(s).getbbox(t)[3] + g for t, s, _c, g in lines)
    y = (H - total) / 2
    for txt, size, colour, gap in lines:
        f = font(size)
        box = d.textbbox((0, 0), txt, font=f)
        d.text(((W - (box[2] - box[0])) / 2, y), txt, font=f, fill=colour)
        y += (box[3] - box[1]) + gap
    img.save(path, quality=92)


def render(raw: list, marks: list, caption_for, out_dir: Path) -> int:
    """Resample onto a fixed grid and burn the caption band into each frame."""
    band = Image.new("RGBA", (W, 104), (20, 18, 14, 176))
    total = int(marks[-1] * FPS)
    j = 0
    for k in range(total):
        t = k / FPS
        while j + 1 < len(marks) and marks[j + 1] <= t:
            j += 1
        src = Image.open(raw[j]).convert("RGB")
        cap = caption_for(t)
        if cap:
            layer = src.convert("RGBA")
            layer.alpha_composite(band, (0, H - 104))
            d = ImageDraw.Draw(layer)
            f = font(34)
            box = d.textbbox((0, 0), cap, font=f)
            d.text(((W - (box[2] - box[0])) / 2,
                    H - 104 + (104 - (box[3] - box[1])) / 2 - 6),
                   cap, font=f, fill=(250, 247, 240, 255))
            layer.convert("RGB").save(out_dir / f"{k + 1:05d}.jpg", quality=92)
        else:
            src.save(out_dir / f"{k + 1:05d}.jpg", quality=92)
    return total


def encode(src: Path, out: Path) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
           "-start_number", "1", "-i", str(src / "%05d.jpg"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg failed ({proc.returncode}):\n{proc.stderr[-1200:]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2]
                                        / "demo-media" / "GEF-mobile-walkthrough.mp4"))
    args = ap.parse_args()
    out = Path(args.out).resolve()

    raw = Path(tempfile.mkdtemp(prefix="walkframes-"))
    work = Path(tempfile.mkdtemp(prefix="walkrender-"))
    try:
        marks: list = []
        count = asyncio.run(capture(raw, marks))

        bounds, acc = [], 0.0
        for cap, _u, sec, _a in STEPS:
            bounds.append((acc, acc + sec, cap))
            acc += sec

        def caption_for(t):
            for a, b, cap in bounds:
                if a <= t < b:
                    return cap
            return ""

        title, body, outro, seq = (work / x for x in ("title", "body", "outro", "seq"))
        for p in (title, body, outro, seq):
            p.mkdir()

        card([("GEF mobile · P14", 30, INK, 26),
              ("一張證書，四個環節", 78, INK, 30),
              ("真實運行 · 香港 · 2026 年 11 月", 28, (90, 84, 72), 0)],
             title / "00001.jpg")
        card([("整個過程，你可以自己走一次", 54, INK, 34),
              ("github.com/JohnnyYau/gef-mobile-credential-portal", 30, (90, 84, 72), 0)],
             outro / "00001.jpg")

        steps = render(sorted(raw.glob("*.jpg")), marks, caption_for, body)

        n = 0
        for k in range(int(TITLE_SEC * FPS)):
            n += 1
            shutil.copy(title / "00001.jpg", seq / f"{n:05d}.jpg")
        for k in range(1, steps + 1):
            n += 1
            shutil.copy(body / f"{k:05d}.jpg", seq / f"{n:05d}.jpg")
        for k in range(int(OUTRO_SEC * FPS)):
            n += 1
            shutil.copy(outro / "00001.jpg", seq / f"{n:05d}.jpg")

        out.parent.mkdir(parents=True, exist_ok=True)
        encode(seq, out)
        print(f"{n} frames out ({n / FPS:.1f}s) from {count} captured")
    finally:
        shutil.rmtree(raw, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)

    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration,size:stream=width,height,nb_frames",
                            "-of", "default=nw=1", str(out)],
                           capture_output=True, text=True)
    print(out.name)
    print(probe.stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
