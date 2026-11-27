"""Ten minutes before the show, check the things that break silently.

Everything here has failed at least once during the build: the tunnel dies with
the machine, the demo hashes drift when the chain is rebuilt, a QR points at the
wrong video, a poster file gets overwritten by a preview. This script looks at
the running system and at the printed artefacts and says, in one screen, which
of them still holds.

    python scripts/preflight.py            # booth checks
    python scripts/preflight.py --tests    # plus the full suite (slow)

Exit code 0 only if every check passes, so it can gate a launcher.
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORTAL = HERE.parent
ROOT = PORTAL.parent
BASE = "http://127.0.0.1:8013"

VALID = ("GFiY4d67yoi8X4wmwnL_8IX18_xo_F7HOQgWBdHZXubNTLhvVX_K1PCWuKZa8cntDWyq5Mn"
         "r7i8yvAopAjxrGQ")
# Fallback only: the live chain is cleared before a show, so the revoked sample
# that exists on stage is whatever the last REVOKE block wrote. `revoked_hash()`
# reads that off the local chain; this constant is the value it had before.
REVOKED = ("8pgPh4z-x2UUzV_eJxU3Eac-n1zblwOoKalGg0Tvf8Hg-7Pj8Vo78QiRrSgahOSLNU0ISvu"
           "rUAwmFaYfGumMIQ")

WANT_QR = ["youtu.be/nVgevH43FYA", "github.com/JohnnyYau/gef-mobile-credential-portal"]

results = []


def check(name: str, fn):
    try:
        ok, detail = fn()
    except Exception as err:                       # a crash is a failed check
        ok, detail = False, f"{type(err).__name__}: {err}"
    results.append((ok, name, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:<38} {detail}")
    return ok


def get(url: str, timeout: float = 15.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def health(url: str):
    status, body = get(url + "/healthz")
    return status, json.loads(body)


def c_local():
    _, h = health(BASE)
    integ = h["checks"]["chain"]["integrity"]
    return (h["status"] == "ok" and integ["ok"],
            f"height {h['height']}, {len(h['signers'])} signers, integrity ok" if integ["ok"]
            else f"integrity bad: {integ['bad_blocks']}")


def c_valid():
    _, body = get(f"{BASE}/api/verify/{VALID}")
    j = json.loads(body)
    # a hash-only lookup reports the issue heights, not a single `height`
    block = (j.get("status", {}).get("issue_heights") or [j.get("height")])[0]
    return j["verdict"] == "VALID ON CHAIN", f"verdict {j['verdict']}, block {block}"


def revoked_hash() -> str:
    """The newest REVOKE on the local chain, falling back to the old constant.

    A show starts from a cleared chain, so any hard-coded hash goes stale the
    moment the chain is rebuilt — the check would report a missing credential
    while the product is perfectly fine.
    """
    blocks = PORTAL / "data" / "demo-chain" / "blocks"
    newest = None
    try:
        for path in sorted(blocks.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8")).get("payload") or {}
            if payload.get("action") == "REVOKE" and payload.get("HashedDocument"):
                newest = payload["HashedDocument"]
    except (OSError, ValueError):
        return REVOKED
    return newest or REVOKED


def c_revoked():
    hashed = revoked_hash()
    _, body = get(f"{BASE}/api/verify/{hashed}")
    j = json.loads(body)
    ok = j["verdict"] == "REVOKED" and j["status"]["revoked"]
    reason = (j.get("reason") or j.get("status", {}).get("reason") or "")
    return ok, f"verdict {j['verdict']}, reason {reason!r}"


def tunnel_url() -> str:
    # utf-8-sig: the file has been written with a BOM before, and a BOM in front
    # of "https://" makes every URL check fail for a reason nobody can see.
    return (PORTAL / "showcase-url.txt").read_text(encoding="utf-8-sig").strip()


def c_tunnel():
    url = tunnel_url()
    if not url.startswith("https://"):
        return False, f"not an https URL: {url}"
    status, h = health(url)
    _, local = health(BASE)
    same = h["chain_name"] == local["chain_name"] and h["height"] == local["height"]
    return status == 200 and same, f"{url} height {h['height']}"


def c_files():
    want = ["P14-A0-Poster.pptx", "P14-A0-Poster.pdf", "P14-A0-Poster-preview.png",
            "P14-Showcase-Deck.pptx", "P14-Mobile-Credential-Verification-Portal.zip",
            "demo-media/GEF-mobile-walkthrough.mp4", "demo-media/GEF-mobile-stage-run.mp4"]
    missing = [w for w in want if not (ROOT / w).exists()]
    return not missing, f"{len(want) - len(missing)}/{len(want)} present" + (
        f", missing {missing}" if missing else "")


def c_stage_qr():
    """The QR the stage paints on the big screen must be scannable off-device.

    It is built from PUBLIC_BASE_URL at request time. If the server was started
    without it (or with 127.0.0.1), every judge who lifts a phone gets nothing —
    while the screen itself looks perfectly fine.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False, "opencv/numpy not installed"
    _, body = get(f"{BASE}/api/qr/{VALID}")
    img = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return False, "QR image did not decode"
    ok, decoded, _pts, _ = cv2.QRCodeDetector().detectAndDecodeMulti(img)
    text = " ".join(d for d in decoded if d) if ok else ""
    host = tunnel_url().split("//", 1)[-1].rstrip("/")
    if host not in text:
        return False, f"QR points at {text[:60] or 'nothing'}, expected host {host}"

    # A clean 610 px read proves the payload, not the optics. A judge photographs the
    # projection from a metre or two, so the same code has to survive a hand-held shot:
    # down to 260 px (what the stage CSS paints), a little motion blur, a JPEG round trip.
    small = cv2.resize(img, (260, 260), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 1.0)
    ok_j, jpeg = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    if not ok_j:
        return False, "could not encode the photo simulation"
    shot, _pts2, _s2 = cv2.QRCodeDetector().detectAndDecode(
        cv2.imdecode(jpeg, cv2.IMREAD_GRAYSCALE))
    if host not in (shot or ""):
        return False, ("readable as a file but not as a 260 px photo — the code is too "
                       "dense to scan off the projector")
    return True, f"encodes {host}/verify?hash=…, still reads as a 260 px photo"


def probe(path: Path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type", "-of", "json", str(path)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:160])
    j = json.loads(out.stdout)
    kinds = [s["codec_type"] for s in j.get("streams", [])]
    return float(j["format"]["duration"]), kinds


def c_videos():
    notes = []
    for name in ("GEF-mobile-walkthrough.mp4", "GEF-mobile-stage-run.mp4"):
        dur, kinds = probe(ROOT / "demo-media" / name)
        if "audio" in kinds:
            return False, f"{name} has an audio stream"
        if dur < 10:
            return False, f"{name} is only {dur:.1f}s"
        notes.append(f"{name.split('-')[-1].replace('.mp4','')} {dur:.0f}s")
    return True, ", ".join(notes)


def c_qr():
    try:
        import cv2
    except ImportError:
        return False, "opencv not installed (pip install opencv-python-headless)"
    img = cv2.imread(str(ROOT / "slides_work_v2" / "poster_assets" / "poster-a0-print.png"))
    if img is None:
        return False, "poster-a0-print.png not readable"
    ok, decoded, _pts, _ = cv2.QRCodeDetector().detectAndDecodeMulti(img)
    found = " ".join(d for d in decoded if d)
    missing = [w for w in WANT_QR if w not in found]
    return not missing, f"{len([d for d in decoded if d])} codes decoded" + (
        f", missing {missing}" if missing else "")


def c_poster_print():
    """The A0 PDF has to survive a print shop, not just a screen.

    Each of these has been wrong at least once: the page was a 2:3 image rather
    than A0, one export left the bottom third blank because the CSS canvas was
    smaller than the window, and a QR was small enough that a phone at arm's
    length could not read it.
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
        import pypdf
    except ImportError:
        return False, "pypdf/PIL/opencv not installed"

    pdf = ROOT / "P14-A0-Poster.pdf"
    png = ROOT / "slides_work_v2" / "poster_assets" / "poster-a0-print.png"
    if not pdf.exists() or not png.exists():
        return False, "poster pdf or print png missing"

    box = pypdf.PdfReader(str(pdf)).pages[0].mediabox
    w_mm, h_mm = float(box.width) / 72 * 25.4, float(box.height) / 72 * 25.4
    if abs(w_mm - 841) > 2 or abs(h_mm - 1189) > 2:
        return False, f"page is {w_mm:.0f}x{h_mm:.0f} mm, not A0"

    im = Image.open(png).convert("RGB")
    px, py_ = im.size
    dpi = px / (w_mm / 25.4)
    if dpi < 140:
        return False, f"only {dpi:.0f} dpi"

    a = np.array(im)
    ink = np.abs(a.astype(int) - np.array([247, 244, 236])).sum(axis=2) > 18
    rows, cols = np.where(ink.any(axis=1))[0], np.where(ink.any(axis=0))[0]
    mm = w_mm / px
    margins = {"left": cols[0] * mm, "right": (px - 1 - cols[-1]) * mm,
               "top": rows[0] * mm, "bottom": (py_ - 1 - rows[-1]) * mm}
    bad = {k: round(v) for k, v in margins.items() if v < 8 or v > 120}
    if bad:
        return False, f"ink margins {bad} mm (8-120 expected)"

    ok, decoded, pts, _ = cv2.QRCodeDetector().detectAndDecodeMulti(cv2.imread(str(png)))
    got = [d for d in decoded if d] if ok else []
    missing = [w for w in WANT_QR if not any(w in d for d in got)]
    if missing:
        return False, f"poster QR missing {missing}"
    small = [round(float(np.linalg.norm(q[1] - q[0])) * mm) for q in pts]
    if min(small) < 25:
        return False, f"a QR is only {min(small)} mm across"
    return True, (f"A0, {dpi:.0f} dpi, margins {min(margins.values()):.0f}-"
                  f"{max(margins.values()):.0f} mm, QR {min(small)}-{max(small)} mm")


def c_copy():
    out = subprocess.run([sys.executable, "scripts/to_traditional.py", "--check"],
                         cwd=PORTAL, capture_output=True, text=True)
    tail = (out.stdout or out.stderr).strip().splitlines()
    return out.returncode == 0, tail[-1] if tail else f"exit {out.returncode}"


def c_zip():
    import zipfile
    z = zipfile.ZipFile(ROOT / "P14-Mobile-Credential-Verification-Portal.zip")
    names = z.namelist()
    need = ["demo-media/GEF-mobile-walkthrough.mp4", "P14-A0-Poster.pdf",
            "P14-Showcase-Deck.pptx", "P14_Learning_Summary.docx"]
    missing = [n for n in need if not any(x.endswith(n) for x in names)]
    return not missing, f"{len(names)} entries" + (f", missing {missing}" if missing else "")


def c_tests():
    out = subprocess.run([sys.executable, "scripts/run_all_tests.py"], cwd=PORTAL,
                         capture_output=True, text=True)
    tail = [l for l in (out.stdout or "").splitlines() if "green" in l or "SUMMARY" in l]
    return out.returncode == 0, (tail[-1].strip() if tail else f"exit {out.returncode}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", action="store_true", help="also run the full suite")
    args = ap.parse_args()

    print(f"portal  {BASE}")
    print(f"tunnel  {tunnel_url()}\n")

    check("local app answers /healthz", c_local)
    check("demo credential still VALID", c_valid)
    check("revoked sample still REVOKED", c_revoked)
    check("public tunnel reaches this instance", c_tunnel)
    check("stage QR scans to the public address", c_stage_qr)
    check("deliverables on disk", c_files)
    check("videos: no audio, sane length", c_videos)
    check("poster QR codes decode to the right URLs", c_qr)
    check("A0 poster is print-ready", c_poster_print)
    check("served copy is Hong Kong Traditional", c_copy)
    check("submission zip is current", c_zip)
    if args.tests:
        check("full test suite", c_tests)

    bad = [n for ok, n, _ in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed")
    if bad:
        print("fix before the show: " + "; ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
