# -*- coding: utf-8 -*-
"""U12 R1: split one index.html into a public page and a staff page.

The staff block (panel-custom .. panel-signers) is one contiguous range, so the
split is a range delete rather than a per-element rewrite. The original file is
copied to baseline/index.pre_u12.html first, so this is reversible.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "verification-portal" / "static"
INDEX = STATIC / "index.html"
BASELINE = STATIC.parent / "baseline"

text = INDEX.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)

BASELINE.mkdir(exist_ok=True)
(BASELINE / "index.pre_u12.html").write_text(text, encoding="utf-8")

# ---- locate anchors -------------------------------------------------------
panel_custom = next(i for i, s in enumerate(lines) if 'id="panel-custom"' in s)
panel_chat = next(i for i, s in enumerate(lines) if 'id="panel-chat"' in s)
chat_comment = panel_chat - 2  # blank line + <!-- CHAT --> above the panel

staff_panels = lines[panel_custom - 1:chat_comment]  # includes leading blank line

# ---- staff page = original with a role banner, no other change ------------
banner = (
    '  <div class="note" id="staffBanner">'
    '教职员页面 Staff console — 只在配置了 ADMIN_TOKEN / ISSUER_TOKEN 时可用。'
    '</div>\n'
)
tabs_at = next(i for i, s in enumerate(lines) if 'class="tabs"' in s)
staff_lines = lines[:tabs_at] + [banner] + lines[tabs_at:]
STAFF = STATIC / "staff.html"
STAFF.write_text("".join(staff_lines), encoding="utf-8")

# ---- public page: drop staff tabs, role cards, panels, registrar.js --------
drop = set()

# tabs (whole <button> lines)
for i, s in enumerate(lines):
    if any(f'data-tab="{t}"' in s for t in ("custom", "issue", "revoke", "signers")):
        drop.add(i)

# role cards: skip from the card opening to its matching closing </div>
for target in ('id="goRegistrar"', 'id="goCustom"'):
    start = next(i for i, s in enumerate(lines) if target in s)
    indent = len(lines[start]) - len(lines[start].lstrip())
    drop.add(start)
    j = start + 1
    while j < len(lines):
        drop.add(j)
        if lines[j].strip() == "</div>" and (len(lines[j]) - len(lines[j].lstrip())) == indent:
            break
        j += 1

# staff panel block
for i in range(panel_custom - 1, chat_comment):
    drop.add(i)

# registrar.js (staff-only behaviour)
for i, s in enumerate(lines):
    if "/static/js/registrar.js" in s:
        drop.add(i)

public = "".join(s for i, s in enumerate(lines) if i not in drop)
INDEX.write_text(public, encoding="utf-8")

print("public lines:", len(public.splitlines()))
print("staff lines:", len(STAFF.read_text(encoding='utf-8').splitlines()))
print("public has panel-issue:", 'id="panel-issue"' in public)
print("public has registrar.js:", "registrar.js" in public)
print("staff has panel-issue:", 'id="panel-issue"' in STAFF.read_text(encoding="utf-8"))
print("backup:", BASELINE / "index.pre_u12.html")
