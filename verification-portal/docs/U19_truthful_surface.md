# U19 — 让系统说实话（对自己、对纸上）

U18 修的是"对外部信任根要硬"。这一轮回头看两个更基础的问题：**系统知道自己有问题，但说不出来；说出来了，也没写在纸上。**

两个缺口都不涉及密码学，都涉及"用户实际看到什么"。

---

## 缺口一：`/healthz` 只说有几个警告，不说是什么

U15 那次坏链事故里，`/healthz` 返回：

```json
"checks": {
  "config": { "fatal": 0, "warnings": 1 }
}
```

数字是 1，但没有任何地方能读到那条警告的正文。当时的处理办法是去 `app/startup.py` 里 grep 所有 `warn(...)` 调用，逐个猜。这在事故现场是不可接受的——**诊断信息被压缩成了一个整数。**

计数必须公开（监控脚本要看），正文不能公开（里面会有路径、密钥文件名、passphrase 变量名）。所以拆成两个端点：

| 端点 | 权限 | 内容 |
|---|---|---|
| `GET /healthz` | 公开 | `config.fatal` / `config.warnings` 只有**计数**（int） |
| `GET /api/diagnostics` | staff（`_admin_required`） | 配置 fatal/warnings **全文**、链完整性、签名者退役边界、版本、uptime |

`/api/diagnostics` 的形状：

```json
{
  "version": { "app": "...", "demo_open": true, "chain": { "height": 4, "integrity": { "ok": true, "bad_blocks": [] } } },
  "uptime_s": 1234.5,
  "chain": {
    "name": "Gef26-credential-chain",
    "height": 4,
    "content_hash_algo": "sha3_512",
    "integrity": { "ok": true, "bad_blocks": [] },
    "signers": [{ "name": "...", "ds_algo": "ML_DSA_65", "sha256fgpt": "...", "retired_at_height": null }]
  },
  "config": { "fatal": [], "warnings": ["...真实文本..."] }
}
```

要点：

- 路由用 `dependencies=[Depends(_admin_required)]`，而不是在函数体里判——这样 OpenAPI 里也能看到它是受保护的。
- `integrity` 复用 `chain_integrity()`（30s 缓存），所以诊断端点不会比 `/healthz` 更贵。
- 签名者带 `retired_at_height`，把 U16 的"退役信任区间"从只能从块里反推，变成可以直接读的一个字段。

8013 上实测到的第一条正文就是真实存在的那条：

```
GEF_KEY_PASSPHRASE is not set but keys exist — signing will fail
```

这条正是 U16 当时只能靠猜的那一条。它现在在页面上（端点），也在文档里。

---

## 缺口二：链坏了，PDF 还是一份干净的报告

U14 已经为**撤销**做过一次同样逻辑的修补：静态文件发出去就改不回来，所以事实必须印在纸上。

链完整性是同一类事实，而且更严重：链上有一个坏块时，所有判定都是 `INVALID`，但 PDF 报告仍然是白纸黑字、格式漂亮、没有任何异常标记的一页。一个人拿着它去应聘，看不出任何区别。

```python
render_diploma_pdf(document, hashed_document, base_url,
                   redact=False, revocation=None, integrity=None)
```

`integrity` 是 `chain_integrity()` 的返回值（`{ok, bad_blocks}`）。`ok is False` 时：

- 22.6mm：朱红加粗 7.8pt — `CHAIN INTEGRITY FAILED: block #12.`
- 19.2mm：7.4pt — `Other blocks on this chain failed to verify; this report's verdict may be unreliable. See /healthz.`
- footer 从 18/14.5mm 下移到 **15.6/12.2mm**，给两行红字让位

三个版本（报告版、admin 完整版、持证人版）都通过 `_credential_pdf` 传入同一个 `chain_integrity()`，所以不存在"某一版忘了画"。

`integrity=None` 表示"没有检查过"，不是"检查通过"——这是刻意的：**只有明确知道 `ok=False` 才印警告，绝不在未知时假装干净，也不在未知时乱报警。** 这个语义和 `/healthz` 里 `integrity` 是 dict 而不是 bool 是同一件事。

---

## 意外收获：PDF 里从来没有二维码

渲染三份 PDF 做目视检查时发现：`report-broken.pdf` 和 `credential-broken.pdf` 的 QR 区域是**空白**。

而 U13 的笔记明确写着"PDF 两版都画 QR"。也就是说，从 U13 到 U18，整整六轮的文档、测试和演示都描述了一个不存在的东西。

定位过程：

1. `qrcode==8.2` 已装，`import qrcode` 成功，`qrcode.make(...).save(io, format="PNG")` 单独跑出 777 字节——生成没问题。
2. 把同样的 `BytesIO` 交给 `canvas.drawImage`：

```
drawImage at buffer end failed: TypeError
  expected str, bytes or os.PathLike object, not BytesIO
```

3. 而绘制段外面套着：

```python
except (OSError, ValueError, TypeError, KeyError):
    pass  # decorative only
```

`TypeError` 正是这个列表里的一员。于是每一次渲染都抛、每一次都被吞掉、每一次都"成功"返回一份没有 QR 的 PDF。

**这是一个用 `except ... pass` 制造出来的谎言。** 注释写着"QR 是装饰性的，hash 照常打印"——错不在"降级"这个决定，错在降级时**没有降级产物**：装饰性元素失败之后，页面上连一个可扫码/可输入的入口都没有了。

修法两层：

```python
c.drawImage(ImageReader(qr_io), W - margin - 28 * mm, y - 44 * mm, ...)
```

`ImageReader` 接受 file-like，类型对上了。这是主路径。

以及一条真正的降级：QR 画不出来（模块缺失、PIL 缺失、图片坏、未来又出现别的类型问题）时，在页面上打印明文 URL：

```
Verify online: http://127.0.0.1:8013/verify?hash=GFiY4d67...
```

按 108 字符硬切行（URL 没有空格，走 `_wrap_text` 的词切分会整行溢出）。

测试锁住两件事：

| 测试 | 断言 |
|---|---|
| `test_the_report_carries_a_scannable_qr` | 页面内嵌图片**恰好 1 张** |
| `test_without_the_qr_module_the_url_still_prints` | patch `pdf_diploma.qrcode = None` 后，文本里出现 `Verify online:` |

第一条是关键：它用一种"数图"的方式，能区分"画了"和"以为画了"。U13 到 U18 之间没有任何一条测试能做到这一点，所以 bug 活了六轮。

---

## 验证

| 项 | 结果 |
|---|---|
| 全量模块 | **34/34 green**（`tests.test_u19_diagnostics` 8 条） |
| 前端 harness | 34/34 |
| 8013 实测 | 11/11（`/api/diagnostics` 401→200、正文可见、`/healthz` 仍只有计数） |
| PDF 目视 | healthy 无红字；broken 两行红字 + QR；credential 版 revocation 框 / 红字 / footer / QR 四块不重叠 |
| QR | `page.images` 从 0 张变为 1 张，页面上可扫 |

三份 PDF 的坐标关系（A4 297mm，从页底起算）：

| 元素 | y 位置 |
|---|---|
| hash 框 | ~`y-9` 至 `y-17` mm |
| QR（28×28mm） | `y-44` 至 `y-72` mm |
| revocation 红框（13mm 高） | 26 至 39 mm |
| integrity 红字 | 22.6 / 19.2 mm |
| footer | 15.6 / 12.2 mm |

revocation 框占 26–39mm，integrity 首行基线 22.6mm（按 2.4mm 字高即到 25.0mm），实际间隙约 1mm；视觉上是两个独立告示，但贴得比较近。U21 把这些数字收进 `LAYOUT` 并加了 `layout_conflicts` 断言（`min_gap=0.8mm`），这条 1mm 的间隙现在由测试守着，改任何一个邻居都会被检查到。

（早期版本的这段文字写成"框底边 39mm 与 22.6mm 之间留 16mm"，把框的**顶边**当成了底边，实际只有约 1mm。公式算错的那一版没有人核对过，正是 U21 要消灭的那类陈述。）

---

## 教训

1. **`except ...: pass` 必须有一个可观察的后果。** 要么计数（`obs.incr`）、要么降级产物（这里就是打印 URL）、要么重抛。三者都没有的 `pass`，等于把 bug 永久的藏起来。
2. **"装饰性"不等于"可以静默失败"。** 判断装饰性的标准不是它重不重要，而是它失败后页面是否还完整。QR 失败的页面并不完整——它失去了唯一的入口。
3. **计数型健康检查会把问题推到人肉 grep。** 公开的给计数，受限的给正文，这个拆分是必要的；只给计数等于没给。
4. **文档里的"已实现"必须有一条能失败的测试兜着。** 否则它会一路被复制到 README、演示脚本和汇报里。

---

## 剩下的真实边界

1. **`/api/diagnostics` 的正文可能包含密钥文件名和路径。** 它已经是 admin-only，但如果将来做"把诊断结果一键分享给支持人员"，需要先脱敏（现在没有这个功能）。
2. **PDF 的 `integrity` 依赖 30s 缓存的 `chain_integrity()`。** 链刚坏掉的 30 秒内，新生成的 PDF 可能仍是干净的。这是缓存换吞吐的代价，不是逻辑漏洞；要更快就得每次重算全链。
3. **QR 指向 `PUBLIC_BASE_URL`。** 如果部署时这个变量填的是内网地址，打印出来的 QR 对外部就是死链。这是部署配置问题，代码不猜。
5. **diagnostics 只有一个链接，不是面板。** staff 页的 Signers 面板底部加了「诊断原文」（`<a href="/api/diagnostics" target="_blank">`，用当前会话 cookie 直接读 JSON）——看得见，但不渲染成表。把配置正文渲染进页面需要先定脱敏规则，所以只做了链接。公开页的 integrity 红条也补了「查看原始检查 →」（U15 遗留）。
