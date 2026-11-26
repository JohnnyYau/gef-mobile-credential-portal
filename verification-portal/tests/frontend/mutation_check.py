"""Mutation check: does the frontend harness actually fail on the pre-fix code?

Copies static/ to a temp dir, undoes the renderBatch escaping there, and runs
the harness against the copy. A harness that still passes would be vacuous.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\verification-portal"
NODE = r"C:\Users\johnn\AppData\Local\Doubao\User Data\sandbox_runtime\bases\fa694f517e5995233c80a9a8db5212c2\node\node.exe"

tmp = tempfile.mkdtemp(prefix="u62-mutation-")
dst = os.path.join(tmp, "static")
shutil.copytree(os.path.join(ROOT, "static"), dst)

target = os.path.join(dst, "js", "verify.js")
src = open(target, encoding="utf-8").read()
needle = '"</td><td>" + esc(r.receipt_id) + "</td><td>" + esc(r.error || r.reason) + "</td></tr>"'
replacement = '"</td><td>" + (r.receipt_id || "") + "</td><td>" + (r.error || r.reason || "") + "</td></tr>"'
if needle not in src:
    print("MUTATION-TEST: needle not found — verify.js changed, update the needle")
    sys.exit(2)
open(target, "w", encoding="utf-8", newline="\n").write(src.replace(needle, replacement))

proc = subprocess.run([NODE, os.path.join(ROOT, "tests", "frontend", "harness.mjs"), dst],
                      capture_output=True, text=True)
print(proc.stdout.strip())
print("exit=" + str(proc.returncode))
shutil.rmtree(tmp, ignore_errors=True)
# The harness must reject the unescaped version: exit 0 here means the test is blind.
sys.exit(0 if proc.returncode != 0 else 1)
