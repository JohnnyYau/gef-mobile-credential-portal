# U17 — 让"缓存后离线判定"这句话成立

U16 的结尾写着"还开着的事"，U17 的起点不是列表上的任何一条，而是 README 里一句已经写了很久的话：

> Employers can cache it and answer "is this revoked?" offline.

这句话在 U17 之前是**假的**。不是"体验不佳"，是链路上少了两样东西，导致签名根本无法被检查。

---

## 签名缺一个 nonce，等于没签

签名消息的定义在 `crypto_util.py` 第 15 行：

```
b64urlsafe( HMAC(key=DSnonce, msg=payloadHash, algo=contentHashAlgo) )
```

`payloadHash` 可以从内容重算，但 `DSnonce` 不能——它是随机生成的密钥材料。**没有 nonce，第三方无法重算被签的消息，也就无法验证签名。**

而 `signer_service.sign_payload` 长这样：

```python
def sign_payload(payload: dict):
    """... Returns (ds_algo, signature_b64) — the nonce is embedded in the payload."""
    algo, priv = _load_signer()
    _, signature = crypto_util.sign_json(payload, algo, priv)
    return algo, signature
```

`sign_json` 把 nonce 返回了，这里**丢掉**了；docstring 说"nonce 嵌在 payload 里"，但没有任何一行代码把 nonce 写进 payload。

块签名没事——`blockchain_util.append_block` 把 `DSnonce` 显式存进块里（第 445 行），块验证读的是 `ds.get("DSnonce")`。**只有状态列表这一条路径走的是 `sign_payload`。**

结果：`GET /api/statuslist` 返回的 `signature` 只有 `algo` / `value` / `signer`。雇主拿到它，能读出"这是 ML-DSA_65 签的"，但没有任何办法确认这个 `value` 是真的。

### 第二处：`signer` 是配置里的名字，不是签名者

```python
payload["signature"] = {"algo": algo, "value": signature, "signer": cfg.SIGNER_NAME}
```

`SIGNER_NAME` 是启动配置（默认 `UNIVERSITY OF UTOPIA`）。U16 加了密钥轮换之后，这条就成了**主动误导**：把 active 切到 `REGISTRAR OFFICE` 之后，状态列表仍然声称是 `UNIVERSITY OF UTOPIA` 签的。一个照着这个名字去找公钥的验证者，会拿错误的钥匙，然后看到"签名无效"——而真正的问题是元数据在撒谎。

### 第三处：没有公钥，就没有"离线"

即使前两处都修好，雇主手里只有列表和签名，没有公钥。`/api/signers` 只给 `sha1fgpt` / `sha256fgpt` / `ds_algo` / `name`——指纹不是钥匙。要验签就得回头请求门户，那"离线"两个字就不成立。

三处合起来是一个完整的闭环缺口，而不是三个独立的小毛病。

---

## 修法

### v2 的签名字段

```json
"signature": {
  "algo": "ML_DSA_65",
  "signer": "REGISTRAR OFFICE",
  "sha256fgpt": "91:71:31:91:...",
  "nonce": "q8Zk...",
  "value": "MEUCIQ..."
}
```

由新的 `sign_payload_envelope(payload)` 生成：它返回 nonce、签名、以及**从签名私钥反推的**名字与指纹（`_load_signer` 拿到 private key → `getfgpt(priv.public_key())` → 在注册表里查 name）。名字跟着钥匙走，不跟着配置走。

`schema` 从 `gef26.statuslist.v1` bump 到 **`v2`**。

为什么 bump 而不是"兼容读取"：v1 的签名本来就不可验证，兼容只会让读者在两种失败之间猜——"是我算错了，还是这份列表天生就验不了？"版本号就是答案：v1 请重新获取。

### `GET /api/signers/keys`

公开端点（不带 admin 头），返回每个签名者的：

```json
{"signers": [{"name", "ds_algo", "sha1fgpt", "sha256fgpt",
              "retired_at_height", "pubkey_pem": "-----BEGIN PUBLIC KEY-----\n..."}],
 "chain": {"name", "height", "content_hash_algo"}}
```

公钥本就存在 `<chain>/keys/signer-<fgpt24>.pem`（`register_signer` 一直在写），此前只是没有任何出口。公开是合理的：公钥不是秘密，而这个端点服务的正是"不信任本门户、但信任这把钥匙"的读者。

`retired_at_height` 一起给出，是为了让验证者自己判断"这份列表是不是由一把当时已退役的钥匙签的"——U16 的边界语义在离线侧同样需要。

### `scripts/verify_statuslist.py`

两个 JSON 文件进，一个结论出，全程不联网、不读链目录：

```powershell
python scripts\verify_statuslist.py statuslist.json anchors.json
python scripts\verify_statuslist.py statuslist.json anchors.json --hash <hash>
```

它按顺序检查七件事，每一条失败都给一句人话：

| 检查 | 失败时的含义 |
|---|---|
| `signature.sha256fgpt` 存在 | 这是 v1 列表，无法验证，请重取 |
| `nonce` / `value` 都在 | 签名不完整 |
| 指纹在 anchor 里 | 签名者不在你信任的名单里 |
| anchor 有条目的 PEM | anchor 缺钥匙 |
| PEM 的指纹 == 条目的指纹 | anchor 放错了钥匙（不是签名错） |
| `signature.algo` == 条目 `ds_algo` | 同一把钥匙两个算法名 |
| 列表高度 ≤ `retired_at_height` | 列表由已退役钥匙在退役后签发 |

最后才做真正的密码学验证（`verify_ds`），payload 取"去掉 `signature` 字段"的整个对象——因为签名是在写入 `signature` 之前对那个对象算的。

`--hash` 的查询有一处刻意的保守：

```python
return {"revoked": False, "trustworthy": bool(ok)}
```

**只有验签通过的列表才被允许回答"未撤销"。** 一份没验过的列表说自己没有某个 hash，什么也证明不了——它可能是旧的、被截断的，或者根本不是这个门户出的。撤销是"存在性证明"，未撤销是"不存在性证明"，后者对数据来源的要求严格得多。

---

## 验证

| 项 | 结果 |
|---|---|
| 全量模块 | **32/32 green**（新增 `tests.test_u17_offline` 6 条） |
| 前端静态 harness | 34/34 |
| 8013 实测（9 项） | 9/9 |
| `smoke_portal.py` | 16 passed / 0 failed |

新增测试覆盖：v2 字段齐全且能验签、切换签名者后指纹与名字跟着变、`/api/signers/keys` 无 token 可读且 PEM 与指纹一致、篡改一条 `revoked` 行导致验签失败、`retired_at_height` 早于列表高度时拒绝、CLI 的三种退出码与 `--hash` 查询。

实测在 **8013 上真跑**：从 HTTP 取两份文档 → 存盘 → CLI 验签 exit 0 → `--hash` 命中已撤销样本 → 一个不存在的 hash 返回 `revoked: false, trustworthy: true` → 改掉一条 reason 后 exit 1。CLI 是子进程执行的，测的是雇主真正会走的那条路径，不是内部函数。

---

## 教训

这一轮最值得记的一点，不是"加了个公钥端点"，而是：

**签名的强度（ML-DSA_65、SHA3-512）和一个签名是否可被验证，是两件不同的事。**

缺一个 nonce，最先进的算法也等于在纸上画了个圈。而"签名者名字来自配置"这种字段，比缺字段更糟——它不是让人验不过，而是让人验错了对象，然后把失败归因到密码学上。

反过来也成立：一旦 nonce、指纹、公钥三样东西齐了，`verify_statuslist.py` 的全部验证逻辑不到 40 行，因为剩下的都只是调用 `verify_ds`。

---

## 仍然开着的事

1. **v1 列表没有迁移路径**，只有"重取"。这在演示项目里没问题；真实部署需要一段双发期（v1 与 v2 并存，v1 标 `unverifiable: true`）。
2. **雇主该多久重取一次**没有写进文档。`Cache-Control: max-age=60` 只管浏览器和代理缓存，不管"离线期间撤销了怎么办"。这是策略问题，不是代码问题。
3. **UI 没有离线校验入口**。`/api/signers/keys` 目前只给 CLI 用；门户前端没有"下载信任根"按钮。
4. **`sign_payload` 本身仍然只返回二元组**，docstring 也还写着"nonce 嵌在 payload 里"（已不准确）。保留它是因为它属于既有内部接口；现在只有 statuslist 走的新路径是安全的。这个 docstring 迟早要改或让该函数退役。
