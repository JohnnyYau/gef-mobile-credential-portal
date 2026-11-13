"""Re-execute notebooks a second time and assert key demo verdicts in outputs."""
import json
import os
import sys

import nbformat
from nbclient import NotebookClient

REPO = os.path.dirname(os.path.abspath(__file__))

EXPECT = {
    "demo-issue.ipynb": [
        "genesis height: 0",
        "FINAL",  # no verdict here; placeholder for structure
        "verify_chain: True",
        "block-000000000.json",
    ],
    "demo-verify.ipynb": [
        "FINAL VERDICT: VALID",
        "FINAL VERDICT: INVALID",
        "verify_chain: False",
        "Signer is trusted",
    ],
    "demo-revoke.ipynb": [
        "FINAL VERDICT: VALID",
        "FINAL VERDICT: INVALID",
        "status after revoke",
    ],
}

TEXT = []


def cell_texts(nb):
    out = []
    for cell in nb.cells:
        if cell["cell_type"] != "code":
            continue
        for o in cell.get("outputs", []):
            if o.get("output_type") == "stream":
                out.append(o.get("text", ""))
            elif o.get("output_type") == "execute_result":
                out.append("".join(o.get("data", {}).get("text/plain", [])))
    return "\n".join(out)


ok = True
for name, needles in EXPECT.items():
    path = os.path.join(REPO, name)
    with open(path, encoding="utf-8") as fh:
        nb = nbformat.read(fh, as_version=4)
    # re-execute (second run) for reproducibility
    NotebookClient(nb, timeout=300, kernel_name="python3").execute()
    with open(path, "w", encoding="utf-8") as fh:
        nbformat.write(nb, fh)

    text = cell_texts(nb)
    TEXT.append((name, text))
    errors = sum(1 for c in nb.cells for o in c.get("outputs", [])
                 if o.get("output_type") == "error")
    print(f"{name}: cells={len(nb.cells)} errors={errors}")
    for needle in needles:
        if needle == "FINAL":
            continue
        if needle not in text:
            ok = False
            print(f"  MISSING: {needle!r}")
        else:
            print(f"  found: {needle!r}")

sys.exit(0 if ok else 1)
