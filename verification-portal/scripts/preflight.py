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


def c_revoked():
    _, body = get(f"{BASE}/api/verify/{REVOKED}")
    j = json.loads(body)
    ok = j["verdict"] == "REVOKED" and j["status"]["revoked"]
    return ok, f"verdict {j['verdict']}, reason {j['reason']!r}"


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
    check("deliverables on disk", c_files)
    check("videos: no audio, sane length", c_videos)
    check("poster QR codes decode to the right URLs", c_qr)
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
