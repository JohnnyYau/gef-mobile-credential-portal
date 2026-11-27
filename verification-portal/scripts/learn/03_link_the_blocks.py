"""站 3 · 區塊怎麼串成一條鏈，改一個字會發生什麼

跑法（在 verification-portal 目錄）：
    .venv\\Scripts\\python.exe scripts\\learn\\03_link_the_blocks.py

你會看到：
  1. 每一塊記住的「前一塊雜湊」，跟我當場重算出來的一不一樣
  2. 在副本上改一個字，第 2 塊立刻對不上 —— 而第 2 塊自己沒被碰過
  3. 整條鏈的驗證結果：哪幾塊紅了、為什麼

注意：全部在 %TEMP% 的副本上做，不動 data/demo-chain。
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from app import blockchain_util, crypto_util           # noqa: E402

CHAIN = ROOT / "data" / "demo-chain"


def hash_of(chain: Path, height: int, algo: str) -> str:
    return crypto_util.hash_json(blockchain_util.load_block(str(chain), height), algo)


def main():
    last = blockchain_util.last_height(str(CHAIN))
    algo = blockchain_util.read_info(str(CHAIN)).get("content_hash_algo", "sha3_512")

    print("=" * 78)
    print(f"1. 這條鏈有 {last + 1} 塊（高度 0 到 {last}），逐塊對「前一塊的雜湊」")
    print("=" * 78)
    for h in range(last + 1):
        block = blockchain_util.load_block(str(CHAIN), h)
        recorded = block.get("prevHashSum", "")
        if h == 0:
            print(f"  區塊 {h}  prevHashSum = ''（創世塊，沒有前一塊）")
            continue
        computed = hash_of(CHAIN, h - 1, algo)
        action = block.get("payload", {}).get("action", "?")
        mark = "OK " if recorded == computed else "不符"
        print(f"  區塊 {h}  {action:<8} 記著 {recorded[:14]}…  重算 {computed[:14]}…  [{mark}]")

    print("\n  → 第 2 塊記住的，就是第 1 塊『整份 JSON』算出來的雜湊。")
    print("     所以第 1 塊連一個空格都不能動，動了第 2 塊就對不上。")

    # ---------------- 副本上篡改 ----------------
    tmp = Path(tempfile.mkdtemp(prefix="chain-tamper-"))
    try:
        copy = tmp / "chain"
        shutil.copytree(CHAIN, copy)

        target = copy / "blocks" / "block-000000001.json"
        block = json.loads(target.read_text(encoding="utf-8"))
        before = block["payload"]["DocumentInfo"]["DocType"]
        block["payload"]["DocumentInfo"]["DocType"] = before + "."
        target.write_text(json.dumps(block, ensure_ascii=False, indent=2), encoding="utf-8")

        print()
        print("=" * 78)
        print(f"2. 在副本上把第 1 塊的 DocType 由「{before}」改成「{before}.」")
        print("=" * 78)
        print(f"  第 1 塊重算雜湊  {hash_of(copy, 1, algo)[:20]}…")
        print(f"  第 2 塊記著的    "
              f"{blockchain_util.load_block(str(copy), 2).get('prevHashSum', '')[:20]}…")
        print("  → 第 2 塊本身一個字都沒改，但它記的號碼已經對不上第 1 塊了。")

        print()
        print("=" * 78)
        print("3. 整條鏈驗一次（verify_chain）")
        print("=" * 78)
        ok, report = blockchain_util.verify_chain(str(copy))
        print(f"  verify_chain -> ok={ok}")
        for row in report:
            checks = row.get("checks", {})
            bad = [name for name, value in checks.items() if value is False]
            if bad or not row.get("ok"):
                print(f"  區塊 {row['height']}  ok={row['ok']}  沒過的項目：{', '.join(bad) or '（無）'}")
        print("\n  → 一處改動，紅的是相鄰的兩塊：自己（簽名失效）＋下一塊（鏈接失效）。")

        print()
        print("=" * 78)
        print("4. 這份被改過的文件，還能驗成「有效」嗎？")
        print("=" * 78)
        from app.chain_core import SAMPLE_DIPLOMA
        result = blockchain_util.verify_document(str(copy), SAMPLE_DIPLOMA)
        for key in ("chain_integrity", "signer_trusted", "on_chain_record",
                    "hash_match", "signature_valid", "not_revoked"):
            print(f"  {key:<18}{result[key]}")
        print(f"  {'valid':<18}{result['valid']}")
        print("\n  → 結論不是「找到可疑」，是「整條鏈本身不可信」，所以一律不給有效。")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"\n（副本已刪：{tmp}）")


if __name__ == "__main__":
    main()

