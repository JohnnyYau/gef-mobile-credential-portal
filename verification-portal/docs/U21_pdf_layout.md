# U21 — 版式是不是对的，不能只靠眼睛

U19 的 QR 事故说明了一个模式：**只要某件事只有"人看 PDF"这一种验证方式，它就会在某轮悄悄坏掉。** U21 把版式本身变成可以断言的数据，并修掉两个只有看图才发现的问题。

---

## 一、常数散在代码里，碰撞只能靠人眼发现

`pdf_diploma.py` 里原来的写法是这样的：

```python
c.roundRect(margin, y - 16 * mm, 170 * mm, 16 * mm, 2 * mm, ...)
c.drawImage(..., y - 44 * mm, width=28 * mm, height=28 * mm, ...)
y0 = 26 * mm
c.roundRect(margin, y0, W - 2 * margin, 13 * mm, ...)
c.drawString(margin, 22.6 * mm, "CHAIN INTEGRITY FAILED: ...")
c.drawString(margin, 15.6 * mm, "...")
```

问一句"QR 会不会压到撤销红框"，唯一的办法是把 PDF 渲染出来看一眼。而这个答案会随任何相邻常数的修改悄悄变化——U19 加红字时就是把 footer 从 18/14.5 挪到 15.6/12.2，靠的是目视确认。

现在所有位置集中在一张表里：

```python
LAYOUT = {
    "hash_box_h": 18.0, "hash_line1_offset": 13.6, "hash_line2_offset": 17.2,
    "qr_size": 28.0, "qr_offset": 47.0, "qr_small_size": 20.0, ...
    "revocation_bottom": 26.0, "revocation_h": 13.0,
    "integrity_main": 22.6, "integrity_note": 19.2,
    "footer_line1": 15.6, "footer_line2": 12.2, "body_floor": 100.0,
}
```

配套两个纯函数：

```python
layout_zones(y_mm, has_revocation=False, has_integrity=False)   # 名称 → (底, 顶)，单位 mm
layout_conflicts(zones, min_gap=0.8)                            # 垂直间隙 < 0.8mm 的成对区域
```

于是"会不会撞"变成一句断言：

```python
self.assertEqual(layout_conflicts(layout_zones(162, has_revocation=True,
                                               has_integrity=True)), [])
```

这里有一个容易自欺的细节：**如果 `layout_conflicts` 永远返回 `[]`，上面这条断言也过。** 所以另有一条元测试——手工构造两个重叠区间，要求它必须报错。否则这个自检函数本身就会变成下一个"看起来很严格"的装饰。

## 二、长字段会把整张卡片挤出页面

行块的高度取决于字段长度。原来的上限只有"每行最多 4 行换行"，没有任何总高度约束。一个长论文标题 + 一段长 observation + 一个长签名行，就能把哈希框、QR 一路往下推，最终 QR 掉进撤销红框区域甚至页外。

修法是显式的**截断**，而不是让下游兜底：

```python
for label, value in rows:
    lines = _wrap_text(value, 10.5, 120 * mm, font=fname)[:4]
    height = (max(1, len(lines)) * 5.2 + 4) * mm
    if y - height < L["body_floor"] * mm:      # 100mm
        truncated = True
        break
```

判断里必须包含**当前这一行**的高度。第一版只检查 `y < floor`，结果最后一行仍然能把 `y` 压到 75mm——测试当场抓到：QR 被跳过、页面只剩 `Verify online:`。这就是"自检要能失败"的同一课。

截断时印一行说明，避免读者以为字段缺失：

```
(fields too long for the card are complete in the embedded JSON)
```

QR 另做两级降级（第二道防线，理论上到不了）：

| 条件 | 行为 |
|---|---|
| `y - 47mm >= 43mm` | 28mm QR |
| 不够，但 `y - 39mm >= 43mm` | 20mm QR |
| 仍不够 | 不画图，打印 `Verify online: <url>` |

## 三、顺手修掉的一个真 bug：哈希第二行印在框外

哈希框原来高 16mm，两行哈希的基线是 `y-14` 与 `y-17.4`：

```
框：  从 y     到 y-16
行一：y-14     （框内）
行二：y-17.4   （框外 1.4mm）
```

86 字符的哈希按 84 切两行，所以最后两个字符（`GQ`）一直印在灰色底块**下方**的白纸上。肉眼扫过去像是"框下面多了两个字母"，不会有人去数。U21 把框改成 18mm，两行都在框内，并且这条关系现在有测试：

```python
self.assertLess(LAYOUT["hash_line2_offset"], LAYOUT["hash_box_h"])
```

## 验证

| 项 | 结果 |
|---|---|
| U21 模块 | 10/10 |
| 全量 | **36/36** |
| 目视 | `credential-broken.pdf`：`GQ` 回到框内、QR 与撤销框/红字/footer 均不重叠 |
| QR | 长字段文档仍为 1 张内嵌图（修复前会退化成纯文本） |

单测覆盖：默认卡片无碰撞、撤销+坏链组合无碰撞、自检能失败、第二行在框内、QR 与框/红带留白、长字段不溢出且仍带 QR、正常卡片不被截断、两行哈希都完整可提取、长字段 + 撤销 + 坏链同时渲染仍是 1 页。

## 教训

1. **"我看过了"不是验证。** 目视能发现一次问题，不能防止它第二次出现；能断言的几何才防得住。
2. **自检函数要有反例测试。** 一个恒为空的碰撞检查比没有更糟——它给人"已经检查过"的错觉。
3. **溢出的正确做法是显式截断 + 说明来源**，不是缩小字号硬塞，也不是让 QR 悄悄消失。
4. **判断边界时要包含当前元素自身的尺寸。** 只看"剩余空间 > 0"会在最后一行失败，这在 40 行代码里就踩了一次。

## 剩下的真实边界

1. **只建模垂直方向。** 这些区域要么全宽、要么贴右边缘，实际会出事的是垂直顺序；横向重叠（例如未来在左侧加东西）没有检查。
2. **文本高度用固定 2.4mm 近似。** 7–11pt 的字实际墨高不同，`min_gap=0.8mm` 是一个保守值，不是精确排版。
3. **没有真正的坐标提取。** 环境里没有 PyMuPDF / pdfplumber，无法从生成的 PDF 反读每个文本块的 y 坐标；现在的做法是"用同一套常数算"，如果绘制代码没走 LAYOUT（有人直接写死数字），测试看不到。代码审查仍需保证"不许出现裸 mm 字面量"。
4. **`body_floor` 是经验值。** 100mm 来自"页高 297 − 顶部内容 − 哈希框 18 − QR 47 − 底部告示带"的余量；若将来卡片再加区块，这个数必须重新推导，而不是微调。
5. **截断只发生在字段行，不在标题/页眉。** 一个 200 字的 IssuingO 仍会横着溢出（`[:44]` 截断了字符数，但没有按宽度截）。这条留给下一轮。
