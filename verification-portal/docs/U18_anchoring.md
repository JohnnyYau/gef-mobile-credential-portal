# U18 — 验签通过，不等于可信

U17 让状态列表变得**可验证**：nonce、指纹、公钥三样齐了，`verify_statuslist.py` 能把一份列表和一个信任根核对起来。

但"核对起来"只证明了这一件事：**这两份文件彼此一致。**

---

## 自洽的假货

雇主的标准动作是：

```
GET /api/statuslist   →  statuslist.json
GET /api/signers/keys →  anchors.json
```

两个请求走同一条通道。如果这条通道被人控制（恶意代理、被劫持的 DNS、改过的镜像），攻击者可以做一件很省力的事：

1. 生成自己的一把钥匙；
2. 用自己的钥匙签一份假列表，把某个已撤销的凭证写成未撤销；
3. 在 `anchors.json` 里只放自己那把钥匙；
4. 两份文件一起送达。

U17 的全部七道检查都会通过：指纹在、nonce 在、PEM 与指纹一致、算法名一致、高度没越界、`verify_ds` 成功。**结论是 `ok: true`，而事实是伪造。**

这不是密码学被攻破，而是**信任的起点被替换了**。ML-DSA 再强，也只保证"这把钥匙签的"，不保证"这把钥匙是学校的"。

---

## 两种补法，强度不同

### `--expect`：硬保证

```powershell
python scripts\verify_statuslist.py statuslist.json anchors.json `
  --expect f2:6d:75:a5:22:38:e9:b4:5f:a6:4f:b4:1b:13:da:d9
```

调用方自己声明"必须是这把钥匙签的"。指纹来自**带外渠道**——学校官网公布的指纹、纸质通知、上一次当面核对过的记录。指纹不属于那两份可能被替换的文件，所以攻击者改不动它。

命中 → 通过；不命中 → 立刻失败，而且失败发生在验签**之前**：

```
signing key 91:71:31:... is not in the expected set (f2:6d:75:...)
```

这条 message 特意把两个指纹都打出来。因为这里最常见的情况不是攻击，而是**密钥轮换之后忘了更新本地期望值**——看到"实际是 91:71，你期望的是 f2:6d"，一眼就知道该改哪边。

`--expect` 可重复给出，用于"我接受这两把中的任意一把"的过渡期。

### `--pin`：信任首次使用（TOFU）

```powershell
python scripts\verify_statuslist.py statuslist.json anchors.json --pin trust-anchor.pin.json
```

第一次运行时，把 anchors 的**指纹集合**写进 pin 文件：

```json
{
  "schema": "gef26.trust-anchor.pin.v1",
  "sha256fgpt": ["91:71:31:91:...", "f2:6d:75:a5:..."],
  "chain_name": "Gef26-credential-chain"
}
```

之后每次运行都必须与这个集合完全相等。输出里带 `anchor_pin` 三态：`created` / `matched` / `mismatch`。

`mismatch` 会分开报"少了谁"和"多了谁"：

```json
{"anchor_pin": "mismatch",
 "removed_since_pin": ["f2:6d:75:..."],
 "added_since_pin": ["aa:bb:cc:dd"]}
```

这是给运维看的：`added` 里出现陌生指纹是警报，`removed` 里有旧指纹可能是正常的钥匙退役。

**记录集合而不是"当前签名者"**，是有意的严格：新增一把钥匙也算变化，即使它还没签过任何东西。理由很直接——如果只锁"当前签名者"，攻击者可以先往 anchors 里塞一把备用钥匙，等你某天轮换到它时一切看起来都正常。集合比对把这种提前埋雷也挡掉，代价是每次真正的轮换都要人工更新 pin（或者用 `--expect` 精确指定）。

---

## 一个容易被做错的决定：坏掉的 pin 不能"重新开始"

最省事的实现是：

```python
if not pin_path.exists() or not is_valid(pin):
    write_pin(...)   # 当作首次使用
```

这条逻辑意味着**删掉 pin 文件就能重置信任**。攻击者不需要伪造任何密码学材料，只需要让你那一次 `--pin` 跑在一个被污染的目录里，或者让 pin 文件"恰好"损坏。

所以现在的实现是失败关闭：

| 情况 | 结果 |
|---|---|
| pin 不存在 | 写入，`created`，通过 |
| pin 内容非法 JSON | `unreadable`，失败 |
| pin 里 `sha256fgpt` 不是列表 | `unreadable`，失败 |
| pin 是空列表 | `unreadable`，失败（空集合等于"信任任何人"，不能当有效 pin） |
| pin 的集合与 anchors 不同 | `mismatch`，失败 |

`unreadable` 的 message 明确写着：

> refusing to treat that as first use

这条拒绝是本轮唯一"宁可让人手动删文件并明确重来，也不自动恢复"的地方。安全默认值的定义就是：便利的那条路径不能由对手触发。

---

## 界面的收尾

Signers 面板底部加了两个下载链接：

- **下载信任根** → `/api/signers/keys`（`download="signer-keys.json"`）
- **下载状态列表** → `/api/statuslist`（`download="statuslist.json"`）

以及一行说明：验签不需要联网、也不需要读这里的链；`--pin` 用于首次锁定，`--expect` 用于已知指纹。这把 U17/U18 的 CLI 能力从"文档里的事"变成"页面上能点的事"。

纯 `<a download>` 实现，没有新增 JS，因为这两个响应本来就是可以直接存盘的 JSON。

---

## 验证

| 项 | 结果 |
|---|---|
| 全量模块 | **33/33 green**（新增 `tests.test_u18_anchor` 8 条） |
| 前端 harness | 34/34 |
| 8013 实测 | 7/7 |
| Signers 面板 | 两个下载链接 + 说明文本实测渲染正确 |

8013 实测覆盖：`--expect` 命中真实签名指纹 → 0；给一个外来指纹 → 1 且指名 expected set；`--pin` 首次 `created` 并落盘；第二次 `matched`；往 anchors 里塞一把 `de:ad:be:ef` → `mismatch` 且 `added_since_pin` 精确列出；把 pin 写成 `{ broken` → `unreadable`（没有重建）；恢复后 `--hash` 仍能命中已撤销样本。

测试模块另覆盖了大小写不敏感的指纹比对、空 pin 列表、以及 `--pin` 与 `--expect` 同时使用的顺序语义。

---

## 剩下的真实边界

1. **pin 文件本身没有完整性保护。** 本机攻击者可以同时改 pin 和 anchors，让两者一致。pin 只防"远程替换"，不防"本地改写"。真正的解法是把 pin 存到调用方控制的位置（CI 的受保护变量、只读介质），这是部署问题。
2. **TOFU 的首次就是弱点。** 如果第一次抓取时通道已被劫持，pin 会锁住假根。所以文档里把 `--expect` 标成硬保证、`--pin` 标成便利版——这个次序不能反。
3. **轮换需要人工介入。** 集合严格比对意味着每次加钥/退役都要更新 pin。可以做一个 `--pin-update` 显式开关，但那等于把"重置信任"变成一个命令，需要配套的审计；本轮没做。——**U20 已补上**：`--pin-update` 只在列表验签通过时改写 pin，并把新旧指纹集合与时间戳追加进 pin 的 `history`（见 `docs/U20_pin_rotation.md`）。
4. **指纹的带外分发还没有载体。** 学校官网模板、海报上的二维码指向什么，目前仍指向验证页而不是指纹列表。这是内容侧的事，不是代码。
