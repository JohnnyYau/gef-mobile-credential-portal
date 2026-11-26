# U20 — 轮换必须是一次有人负责的动作

U18 的 `--pin` 是严格的：anchors 的指纹集合一变，就失败。这对攻击是对的，对**合法的密钥轮换**是错的——轮换之后唯一的"修复办法"是删掉 pin 文件，而这正是 U18 花一整轮去堵的行为（"删文件即可重置信任"）。

U20 把这个重置变成一条命令，而且是一条不能悄悄做的命令。

---

## 三条性质

### 1. 只在列表验签通过时才改写 pin

顺序被刻意安排成这样：

```
pin 比对失败 → 记下 diff（不改盘）
              ↓
        验签列表（+ --expect 若给了）
              ↓
    通过？ 是 → 写 pin + 追加 history
           否 → 保持原 pin，anchor_pin=mismatch，reason 里说明未更新
```

为什么不能"先更新再看"：攻击者控制的通道同时送来假 anchors 和假列表。如果 `--pin-update` 允许在验签失败时写入，那攻击者只要让你跑一次带 flag 的命令，就永久锁住了他的钥匙——**一次失误变成永久失守**。先验签，是把"这次更新至少代表一份密码学上自洽的列表"作为最低门槛。

注意这个门槛并不高：自洽的假列表也能通过（这正是 U18 说的）。所以第 3 条不是装饰。

### 2. 变更写进 pin 自己的 history

pin 从 v1 升到 v2：

```json
{
  "schema": "gef26.trust-anchor.pin.v2",
  "sha256fgpt": ["91:71:31:...", "de:ad:be:ef"],
  "chain_name": "Gef26-credential-chain",
  "history": [
    {
      "at": "2026-11-21T00:14:03+00:00",
      "previous": ["91:71:31:..."],
      "added": ["de:ad:be:ef"],
      "removed": [],
      "tool": "verify_statuslist.py --pin-update"
    }
  ]
}
```

`previous` 存的是**上一轮的完整集合**，不是 diff——这样任何一条 history 记录都能独立回答"当时信任的是谁"。多条轮换会追加而不是覆盖（有测试）。

v1 的 pin 仍然可读：指纹集合才是关键，旧文件不会因为升级而失效，只在下一次真正更新时才写成 v2。

### 3. 没给 `--expect` 就报警

`--pin-update` + 没有 `--expect`，输出里带：

```
"warning": "no --expect was given: the new key is vouched for only by the same
            channel that delivered the anchor"
```

不阻断——因为有人可能就是靠打电话核对指纹后手工执行。但这条警告必须出现，否则日志里会留下一条"曾经把一把来路不明的钥匙提升为信任根"的记录，而看不出当时有没有人真的核对过。

给了命中 `--expect` 时，这个字段不出现。

---

## 仍然是失败关闭的两处

| 情形 | 行为 |
|---|---|
| pin 坏 JSON / 空集合 | `unreadable`，**`--pin-update` 也不重置**（"treating that as first use" 仍是攻击） |
| pin 不存在 | 视为首次使用：`created`（本来就没有历史可保护） |
| anchors 变了，列表验签失败 | `mismatch`，pin 文件字节不变 |
| anchors 变了，列表验签通过，但没给 flag | `mismatch`，reason 里提示 `--pin-update` |

第二行是唯一"自动写盘"的路径，和 U18 一样：首次使用没有可对照的过去。

写入用临时文件 + `os.replace`：

```python
tmp = target.with_name(target.name + ".tmp")
tmp.write_text(...)
tmp.replace(target)
```

因为"半个 pin 文件"在本工具里等于永久失效（坏 JSON 被 fail closed），一次崩溃不能造出那个状态。

---

## 验证

| 项 | 结果 |
|---|---|
| 全量模块 | **35/35 green**（`tests.test_u20_pin_update` 11 条） |
| 8013 实测 | 10/10（真实 statuslist + anchors 文件，含一次模拟轮换） |
| 前端 harness | 34/34 断言 |

单测覆盖的关键分支：

- 只给 `--pin-update` 不给 `--pin` → argparse 报错（exit 2），不是静默忽略；
- 轮换但不给 flag → `mismatch`，reason 点名 flag；
- 轮换 + flag + `--expect` → `updated`，pin 落 v2，history 一条，`previous` 等于改动前的集合；
- 更新后再跑 → `matched`，history 不重复增长；
- 两次轮换 → history 两条，`history_length` 为 2；
- 无 `--expect` → 有 `warning`；有命中 `--expect` → 无 warning；
- 篡改列表 body + 轮换 + flag → 拒绝更新，pin 字节不变；
- 坏 pin + flag → `unreadable`，文件内容原样保留；
- v1 pin 先 `matched`，轮换后可升 v2；
- 写盘后目录里没有 `.tmp` 残留。

实机那次跑的是同一套动作，只是文件来自 `/api/statuslist` 与 `/api/signers/keys` 而非测试夹具：第一次 `created`，第二次 `matched`，追加一个 `de:ad:be:ef` 后 `mismatch`，带 flag 后 `updated`（`added: ["de:ad:be:ef"]`，`history_length: 1`），再跑 `matched`。

---

## 教训

1. **严格的安全规则如果没给出路，人就会走最烂的那条路。** 删文件不是"绕过"，是唯一可用的操作。把出路做成命令，才能把它变成可审计的行为。
2. **更新信任根时，"验签通过"只是入场券。** 真正的保证来自 `--expect`；history 只解决"事后能不能看出发生过什么"，不解决"当时该不该发生"。
3. **原子写不是洁癖。** 在一个"坏文件 = 永久锁死"的设计里，非原子写会把一次崩溃升级成一次不可恢复的信任重置失败。

---

## 剩下的真实边界

1. **history 是自述，不是证明。** 本机攻击者可以连 pin 一起改（把 history 洗掉、无缝替换集合）。pin 与 history 都只防"远程替换"。要防本地改写，pin 必须放在调用方控制的只读位置（CI 受保护变量、只读介质、纸质记录）。
2. **`--pin-update` 的判断责任在人。** 工具能保证"列表自洽、变更留痕、没核对指纹时有警告"，不能保证"新钥匙真的属于学校"。这个决定必须来自带外信息。
3. **history 无上限。** 每次轮换加一条，几十年也不会大到值得截断；如果将来真的需要，应该是"归档旧 history 到独立文件"，而不是悄悄裁剪。
4. **`--pin-update` 不联动 `--pin` 之外的信任载体。** 如果有人同时把 pin 抄进了 CI 变量，CLI 更新不了那份副本，两边会静默分叉。这是部署流程问题，本轮没做同步机制。
