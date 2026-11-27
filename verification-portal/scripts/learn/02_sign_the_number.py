"""站 2 · 一個號碼怎麼被簽，為什麼要包一層 nonce

跑法（在 verification-portal 目錄）：
    .venv\\Scripts\\python.exe scripts\\learn\\02_sign_the_number.py

你會看到：
  1. 第 1 塊裡那條簽名記錄長什麼樣
  2. 只用「公鑰」就能驗回 True —— 這就是別人驗你的方式
  3. 改一個字，同一個公鑰立刻驗不過
  4. 同一份文件簽兩次，簽名不一樣 —— nonce 的作用
"""

import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization   # noqa: E402

from app import blockchain_util, crypto_util              # noqa: E402

CHAIN = ROOT / "data" / "demo-chain"
HEIGHT = 1


def key_paths(fgpt: str):
    stem = "signer-" + fgpt.replace(":", "")[:24]
    return CHAIN / "keys" / f"{stem}.pem", CHAIN / "keys" / f"{stem}.priv.pem"


def main():
    block = blockchain_util.load_block(str(CHAIN), HEIGHT)
    payload = block["payload"]
    ds = block["DataSignatureInfo"][0]
    pub_path, priv_path = key_paths(ds["DSsha256fgpt"])

    print("=" * 78)
    print(f"1. 第 {HEIGHT} 塊的簽名記錄（DataSignatureInfo[0]）")
    print("=" * 78)
    for field in ("DSAlgo", "DSsha256fgpt", "DSnonce", "DSscheme"):
        print(f"  {field:<16}{ds[field]}")
    print(f"  {'DSignature':<16}{ds['DSignature'][:44]}…  （共 {len(ds['DSignature'])} 字元）")
    print(f"  {'DSmessageDigest':<16}{ds['DSmessageDigest'][:44]}…")

    pub = crypto_util.fetch_pubkey(str(pub_path))
    algo = block.get("contentHashAlgo", "sha3_512")

    print()
    print("=" * 78)
    print("2. 只用公鑰驗一次（跟陌生人驗你的方式一樣）")
    print("=" * 78)
    ok = crypto_util.verify_ds(payload, ds["DSAlgo"], pub, ds["DSignature"],
                               ds["DSnonce"], content_hash_algo=algo)
    digest = crypto_util.message_digest_b64(payload, ds["DSnonce"], algo)
    print(f"  verify_ds(...)                 -> {ok}")
    print(f"  重算 messageDigest 與鏈上一致   -> {digest == ds['DSmessageDigest']}")
    print("\n  → 我手上只有公鑰檔（.pem，451 bytes），沒有私鑰，也能確認是他簽的。")

    print()
    print("=" * 78)
    print("3. 改一個字再驗（DocType 後面加一個句號）")
    print("=" * 78)
    bad = json.loads(json.dumps(payload))
    bad["DocumentInfo"]["DocType"] = payload["DocumentInfo"]["DocType"] + "."
    bad_ok = crypto_util.verify_ds(bad, ds["DSAlgo"], pub, ds["DSignature"],
                                   ds["DSnonce"], content_hash_algo=algo)
    print(f"  改過的 payload verify_ds(...)   -> {bad_ok}")
    print("\n  → 簽名是對『那一份內容』的承諾，內容一動，承諾就失效。")

    print()
    print("=" * 78)
    print("4. 同一份內容簽兩次（這次要有私鑰才做得到）")
    print("=" * 78)
    priv_data = priv_path.read_bytes()
    priv = serialization.load_pem_private_key(priv_data, password=None)
    n1, s1 = crypto_util.sign_json(payload, ds["DSAlgo"], priv, content_hash_algo=algo)
    n2, s2 = crypto_util.sign_json(payload, ds["DSAlgo"], priv, content_hash_algo=algo)
    print(f"  第一次 nonce {n1[:16]}…  簽名 {s1[:24]}…")
    print(f"  第二次 nonce {n2[:16]}…  簽名 {s2[:24]}…")
    print(f"  兩次簽名一樣嗎                 -> {s1 == s2}")
    print(f"  兩個簽名都驗得過嗎             -> "
          f"{crypto_util.verify_ds(payload, ds['DSAlgo'], pub, s1, n1, algo) and crypto_util.verify_ds(payload, ds['DSAlgo'], pub, s2, n2, algo)}")

    print()
    print("=" * 78)
    print("5. 把簽名搬到另一個 nonce 上用（模擬重放）")
    print("=" * 78)
    replay = crypto_util.verify_ds(payload, ds["DSAlgo"], pub, s1, n2, algo)
    print(f"  用 s1 配 n2 去驗                  -> {replay}")
    print("\n  → 簽名綁死在那個 nonce 上。換了 nonce，簽名就不認。")
    print("     所以同一份文件每次簽出來的東西都不同，抄走別人的簽名沒有用。")


if __name__ == "__main__":
    main()

