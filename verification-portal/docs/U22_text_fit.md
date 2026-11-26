# U22 — 字符数不是宽度

U21 把纵向位置变成了可断言的数据，但**横向**从来没被算过。三处都在赌"用户的名字不会太长"：

```python
c.setFont(_font_for(di.get("IssuingO", "UNIVERSITY")[:44], bold=True), 20)
c.drawString(margin, H - 20 * mm, di.get("IssuingO", "UNIVERSITY")[:44])
```

```python
words = str(text).split()
trial = (cur + " " + w).strip()
if stringWidth(trial, font, size) <= width: ...
```

```python
c.drawString(margin, 15.6 * mm,
             "This is a verification report for an on-chain hash. Identity fields are withheld.")
```

三处的问题各不相同，但答案是同一个：**画之前先量。**

---

## 一、`[:44]` 是字符数，不是毫米

20pt 下：

- 44 个拉丁字母 ≈ 150mm，刚好贴着 170mm 的可写宽度；
- 44 个汉字 ≈ **310mm**，比 A4 的 210mm 还宽 100mm。

同一行代码，对英文是"有点挤"，对中文是"必然出页"。而这张卡片本来就面向中文凭证（`IssuingO` 完全可能是「香港理工大學電子及資訊工程學系」）。

```python
def _fit_text(text, size, width, font="Helvetica", ellipsis="..."):
    """二分找到能放下的最长前缀，加省略号。"""
    s = str(text)
    if stringWidth(s, font, size) <= width:
        return s
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if stringWidth(s[:mid] + ellipsis, font, size) <= width:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo] + ellipsis
```

二分而不是"每次去掉一个字符"：后者对 300 字符的串要做 300 次 `stringWidth`，而渲染 PDF 是在请求路径上跑的。

现在所有单行文本都过这道闸门：机构名（20pt）、部门（11pt）、文档类型（15pt）、撤销标题与理由（11/8.5pt）、完整性两行（7.8/7.4pt）、footer 两行（8pt）。

## 二、`_wrap_text` 遇到超宽单词时直接放弃

原来的逻辑：按空格切词，能塞就塞，塞不下就换行。但**一个词本身就比列宽还宽**时，`cur = w` 之后的判断永远失败，最后整词单独占一行——宽度就是它自己的宽度。

现实输入：300 字符没有空格的学号、一个长 URL、一串 `A`。这类值不会因为"没有空格"就变短。

修法是字符级硬断：

```python
if stringWidth(w, font, size) > width:
    if cur:
        lines.append(cur)
        cur = ""
    chunk = ""
    for ch in w:
        if chunk and stringWidth(chunk + ch, font, size) > width:
            lines.append(chunk)
            chunk = ch
        else:
            chunk += ch
    cur = chunk
```

只有超宽 token 会走这条路，正常句子仍然按词换行（有测试断言 `" ".join(lines) == 原文`，防止硬断逻辑误伤普通文本）。

## 三、写死的长句也需要量

footer 和完整性说明是常量，看起来"永远放得下"，但它们是**文案**——改一个字、加一句解释，就可能越界，而没有任何机制会提醒。

它们现在也过 `_fit_text`，并且有一条测试把这几句话连同字号一起列出来，直接断言宽度：

| 文本 | 字号 | 要求 |
|---|---|---|
| `This is a verification report for an on-chain hash...` | 8 | ≤ 170mm |
| `The credential PDF is issued to its holder through...` | 8 | ≤ 170mm |
| `Upload it to the verification portal for the cryptographic verdict...` | 8 | ≤ 170mm |
| `Other blocks on this chain failed to verify...` | 7.4 | ≤ 170mm |
| `VERIFICATION REPORT — identity withheld...` | 8.5 | ≤ 170mm |

这条测试的价值不在"现在过"，而在**下一次改文案时会失败**。

## 验证

| 项 | 结果 |
|---|---|
| U22 模块 | 13/13 |
| 全量 | **37/37** |
| 渲染 | 超长机构名 → 单页、含 `...`、不抛异常；300 字符学号 → 换行且 QR 仍在 |

单测覆盖：短文本原样返回、超宽文本被截断且宽度达标、44 字中文被截断（不再按字符数）、空串、恰好等宽时**不**截断、超宽 token 被拆、普通句子不被打断、三种列宽（60/120/170mm）下每行宽度达标、长机构名按自身字号达标、长学号不毁掉 QR、固定长句清单、以及"拟合不影响 U21 的版式下限"。

## 教训

1. **字符数是最容易写、最没有意义的约束。** 同样的 `[:44]` 在不同字体、不同字号、不同语言下相差一倍以上。
2. **"常量文案不会溢出"是假设，不是事实。** 只要它由人编辑，就需要度量。
3. **换行函数的边界条件是"单词比行宽还宽"。** 这在英文里罕见（长 URL 除外），在中文里根本不会发生（中文习惯按字断行），所以它长期只影响少数输入——直到有人贴进一串哈希。
4. **度量成本要算进请求路径。** 二分 8 次 `stringWidth` 可以接受，逐字符 300 次不行。

## 剩下的真实边界

1. **`_fit_text` 的字体参数决定度量结果。** 页眉用 `_font_for` 选到 CJK 字体时，传进去的也是该字体名，但 CJK 字体的 `stringWidth` 依赖 reportlab 内建的 CID 度量（近似等宽），与真实 TrueType 字体可能有偏差。宽度是保守估计，不是精确排版。
2. **省略号固定是 `...`（3 个 ASCII 点）**，不用 `…`：后者在部分 CID 字体里缺字形。代价是极窄宽度下可能只剩 `...`——此时该行已无信息量，但也不会出页。
3. **提取文本无法按字号验证。** `pypdf` 只给字符序列，不给字号/坐标；所以"渲染后再量"这条路径做不了，只能对"送进去的字符串 + 字号"做断言。真正的坐标级验证需要 PyMuPDF，环境里没有。
4. **行内混排没有处理。** 目前每行只有一种字号；若将来在同一行混排粗体+常规（例如 `REVOKED ON CHAIN — block #4` 想把 `block #4` 换成常规体），宽度要按片段分别累计。
5. **`_fit_text` 只保证不出页，不保证好看。** 一个被截成 `UNIVERSITY OF...` 的机构名读起来是残缺的；要真正好看需要自动缩放字号，那会牵动已固定的行高与版式下限，本轮没做。
