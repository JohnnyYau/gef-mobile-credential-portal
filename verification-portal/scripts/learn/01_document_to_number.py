"""站 1 · 一份文憑怎麼變成一個號碼

跑法（在 verification-portal 目錄）：
    .venv\\Scripts\\python.exe scripts\\learn\\01_document_to_number.py

它做三件事，你只需要看輸出：
  1. 把一份真文憑切成三段，各算一個雜湊
  2. 三段再合成一個根 —— 這就是鏈上那個 HashedDocument
  3. 改一個字，四個號碼全部變
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]           # verification-portal/
sys.path.insert(0, str(ROOT))

from app import blockchain_util, crypto_util           # noqa: E402
from app.chain_core import SAMPLE_DIPLOMA             # noqa: E402

CHAIN = ROOT / "data" / "demo-chain"
SHORT = 18


def show(title, value):
    print(f"  {title:<34}{value[:SHORT]}…{value[-6:]}")


def numbers(doc):
    parts = []
    for section in ("PersonalParticulars", "AcademicInfo", "DocumentInfo"):
        h = crypto_util.hash_json(doc[section])
        parts.append((section, h))
    root = crypto_util.merkle_root([h for _, h in parts])
    return parts, root


def main():
    doc = SAMPLE_DIPLOMA

    print("=" * 78)
    print("1. 這份文憑長什麼樣（三段，不多不少）")
    print("=" * 78)
    for section, body in doc.items():
        keys = ", ".join(body.keys())
        print(f"  {section:<24}[{keys}]")

    print()
    print("=" * 78)
    print("2. 每一段各自算一個雜湊（sha3-512，base64url）")
    print("=" * 78)
    parts, root = numbers(doc)
    for section, h in parts:
        show(section, h)
    print()
    show("合併成一個根 HashedDocument", root)

    print()
    print("=" * 78)
    print("3. 跟鏈上第 1 塊對一次（如果對不上，這裡會直接報錯）")
    print("=" * 78)
    payload = blockchain_util.load_block(str(CHAIN), 1)["payload"]
    pairs = [
        ("HashedPersonalParticulars", parts[0][1]),
        ("HashedAcademicInfo", parts[1][1]),
        ("HashedDocumentInfo", parts[2][1]),
        ("HashedDocument", root),
    ]
    for field, mine in pairs:
        theirs = payload.get(field, "")
        mark = "OK " if theirs == mine else "不同"
        print(f"  [{mark}] {field:<30}{mine[:SHORT]}…")
    assert all(payload.get(f) == v for f, v in pairs), "鏈上資料與本機重算不符"
    print("\n  → 你在自己電腦上算出來的號碼，跟鏈上一模一樣。")

    print()
    print("=" * 78)
    print("4. 現在改一個字：Surname 由 CHAN 改成 CHAN.")
    print("=" * 78)
    changed = json.loads(json.dumps(doc))
    changed["PersonalParticulars"]["Surname"] = "CHAN."
    new_parts, new_root = numbers(changed)
    print(f"  PersonalParticulars\n    原本 {parts[0][1][:SHORT]}…\n    改後 {new_parts[0][1][:SHORT]}…")
    print(f"  HashedDocument\n    原本 {root[:SHORT]}…\n    改後 {new_root[:SHORT]}…")
    same = sum(1 for (_, a), (_, b) in zip(parts, new_parts) if a == b)
    print(f"\n  三段之中只有 {same} 段沒變（改了 Surname，只動到 PersonalParticulars）。")
    print("  但根一定變 —— 根變，鏈上就找不到這個號碼。")
    print("\n  這就是「改一個字就看得出來」的全部原理，沒有魔法。")


if __name__ == "__main__":
    main()
