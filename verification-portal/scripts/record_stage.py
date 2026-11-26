"""Record the stage page as it actually runs, without touching the desktop.

Chrome's DevTools protocol can stream frames (Page.startScreencast) from a
headless tab, so the recording is the real page at real speed and the user's
screen is never involved. Frames land in a temp dir, ffmpeg turns them into an
MP4, and the script reports the frame count and duration it actually got.

    python scripts/record_stage.py --out ..\\demo-media\\stage-run.mp4

Notes:
- the page runs the four real calls, so this spends two blocks on the chain;
- frames arrive only when the page repaints, so the encoder is told a variable
  input rate and pads to a constant output rate.
"""

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import websockets

HERE = Path(__file__).resolve().parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


async def cdp(ws, msg_id, method, **params):
    await ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
    while True:
        raw = json.loads(await ws.recv())
        if raw.get("id") == msg_id:
            if "error" in raw:
                raise RuntimeError(f"{method}: {raw['error']}")
            return raw.get("result", {})


async def record(url: str, seconds: float, fps: int, out_dir: Path) -> int:
    """Grab the tab at a steady rate.

    Page.startScreencast only emits frames when the page repaints, which for a
    mostly-static stage screen means about one frame per second — a slideshow,
    not a recording. Page.captureScreenshot on a fixed interval is slower per
    frame but gives honest, evenly spaced motion.
    """
    interval = 1.0 / fps
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--remote-debugging-port=9333", "--window-size=1600,900",
        f"--user-data-dir={tempfile.mkdtemp(prefix='rec-')}",
        "--no-first-run", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        target = None
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:9333/json", timeout=1) as r:
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
            await cdp(ws, 1, "Page.enable")
            await cdp(ws, 2, "Emulation.setDeviceMetricsOverride",
                      width=1600, height=900, deviceScaleFactor=1, mobile=False)
            await cdp(ws, 3, "Page.navigate", url=url)

            # capture only once the document is actually there; grabbing during
            # navigation fails with "Not attached to an active page".
            for wait in range(40):
                state = await cdp(ws, 10 + wait, "Runtime.evaluate",
                                  expression="document.readyState", returnByValue=True)
                if state.get("result", {}).get("value") == "complete":
                    break
                await asyncio.sleep(0.25)
            await asyncio.sleep(0.6)

            loop = asyncio.get_running_loop()
            deadline = loop.time() + seconds
            n, msg_id = 0, 100
            while loop.time() < deadline:
                tick = loop.time()
                msg_id += 1
                try:
                    shot = await cdp(ws, msg_id, "Page.captureScreenshot",
                                     format="jpeg", quality=90, fromSurface=True)
                except RuntimeError:
                    await asyncio.sleep(0.1)
                    continue
                n += 1
                (out_dir / f"{n:05d}.jpg").write_bytes(base64.b64decode(shot["data"]))
                sleep = interval - (loop.time() - tick)
                if sleep > 0:
                    await asyncio.sleep(sleep)
        return n
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def encode(frames_dir: Path, out: Path, fps: int) -> None:
    frames = sorted(frames_dir.glob("*.jpg"))
    if not frames:
        raise SystemExit("no frames captured")
    # frames are already evenly spaced by the capture loop, so read them at the
    # same rate they were taken.
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(fps), "-start_number", "1",
        "-i", str(frames_dir / "%05d.jpg"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        "-movflags", "+faststart", str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg failed ({proc.returncode}):\n{proc.stderr[-1200:]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8013/showtime?auto=1&token=demo-staff-token")
    ap.add_argument("--seconds", type=float, default=22.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out", default=str(HERE.parent.parent / "demo-media" / "stage-run.mp4"))
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = Path(tempfile.mkdtemp(prefix="stageframes-"))
    try:
        n = asyncio.run(record(args.url, args.seconds, args.fps, frames_dir))
        print(f"captured {n} frames")
        encode(frames_dir, out, args.fps)
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
         "-of", "default=nw=1", str(out)],
        capture_output=True, text=True)
    print(out.name, probe.stdout.strip().replace("\n", "  "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
