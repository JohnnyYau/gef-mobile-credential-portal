# U6 验收报告 — 前端工程化与 XSS 审计

批次：`CODE_UPGRADE_PLAN.md` U6（U6.1 文件拆分 / U6.2 XSS 审计 / U6.3 前端测试）
日期：2026-11-13
状态：**U6.1 / U6.2 / U6.3 全部完成**；16 模块 202 条测试双后端全绿。

---

## 0. 一句话结论

`static/index.html` 从 **1799 行单体**（内联样式 + 单个 1217 行 `<script>`）拆成 **392 行外壳 + 200 行 CSS + 8 个按标签页划分的经典脚本**，并补上**本来就缺失的 `/static` 挂载**；29 处 `innerHTML` / 1 处 `document.write` 逐处定性，**发现并修掉 7 个真实注入面**（含 PDF 文本层 warnings、CSV 行数据、文件名、批量验证 error）；转义函数从"依赖 DOM 的取巧手法"改成纯字符串实现，并配**能证明自己不是摆设的 Node 断言套件**（34 条断言 + 变异测试）。

---

## 1. 改动文件清单（路径 + 行号）

### 1.1 新增（计划内允许新建的前端资产与测试）

| 路径 | 行数 | 来源 | 内容 |
|---|---|---|---|
| `static/css/portal.css` | 200 | 原 `index.html` 8–204 行 | 全部样式，机械切片 |
| `static/js/core.js` | 46 | 580–601、1026–1033 | `$` / `api()` / `showErr` / `hideErr` / `escapeHtml` / `esc` / `downloadText` + 共享状态 |
| `static/js/format.js` | 198 | 603–715、832–839、869–907、1222–1239、1361–1376 | 判定翻译、六项检查表、持有人表、收据、QR、小时图表 |
| `static/js/verify.js` | 250 | 771–868、1105–1164、1437–1531 | 样例、批量验证、文档/编号/PDF 验证、dropzone、PDF 自动填充 |
| `static/js/registrar.js` | 375 | 908–1104、1165–1221、1270–1320、1713–1780 | API Key、CSV 批量签发、单笔签发/注销、签发方、自制凭证 |
| `static/js/student.js` | 32 | 1240–1269 | 学生自助查询 |
| `static/js/log.js` | 59 | 1321–1360、1377–1392 | 公开日志、异常监控、通知记录 |
| `static/js/chat.js` | 115 | 1600–1712 | 对话、人物卡、联网卡、来源列表 |
| `static/js/main.js` | 184 | 716–770、1393–1415、1416–1436、1532–1599、1781–1795 | 标签路由、版本横幅、健康/样例、DOM 接线、boot |
| `static/index.legacy.html` | 1798 | 原文件副本 | 回滚基线（计划要求的"保留单文件版本"） |
| `tests/test_frontend.py` | 164 | 新增 | 12 条 Python 测试（外壳/资产/挂载/JS 语法/转义套件/变异测试） |
| `tests/frontend/harness.mjs` | 167 | 新增 | 无依赖 Node 载体：假 DOM + 路由 stub + 一个 VM realm |
| `tests/frontend/assertions.js` | 79 | 新增 | 26 条同步断言（在 portal realm 内执行） |
| `tests/frontend/mutation_check.py` | 34 | 新增 | 变异测试：临时副本还原一处修复，断言套件必须变红 |

### 1.2 修改

| 路径 | 行号 | 改动 |
|---|---|---|
| `static/index.html` | 8（原 8–204） | 整块 `<style>` → `<link rel="stylesheet" href="/static/css/portal.css">` |
| `static/index.html` | 382–389 | 原 579–1796 `<script>` → 8 个 `<script src="/static/js/*.js">`（顺序 core→format→verify→registrar→student→log→chat→main） |
| `app/main.py` | 34 | `from fastapi.staticfiles import StaticFiles` |
| `app/main.py` | 240–244 | 新增 `app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")` |
| `static/js/core.js` | 21–33 | `esc()` 由 `createElement→textContent→innerHTML` 改为 `escapeHtml()` 纯字符串实现 |
| `static/js/verify.js` | 73–79 | `renderBatch`：`row` / `hash` / `receipt_id` / `error` / `reason` 全部转义 |
| `static/js/verify.js` | 231–237 | PDF 提取：`warnings` 逐条 `esc` 后再 join，低置信度字段名同改 |
| `static/js/verify.js` | 245 | 提取失败分支：`esc(friendlyErr(e.message))` |
| `static/js/registrar.js` | 26–27 | `loadApikeys`：`name` / `id` / `data-revoke` 转义 |
| `static/js/registrar.js` | 154、157 | 批量预览：`r.row` 转义 |
| `static/js/registrar.js` | 180–183 | 批量签发结果：`pdf_url` / `qr_url` / `hash` / `row` 转义 |
| `static/js/registrar.js` | 331–337 | 自制凭证结果卡：`hash` / `height` / `output_dir` / 三个 URL / `file_id` 转义 |
| `static/js/registrar.js` | 368–370 | 自制凭证列表：`name` / `pdf_url` / `json_url` 转义 |
| `static/js/log.js` | 16、31、35–36 | 高度 / 阈值 / 计数 / 最后区块 等数值入 DOM 前统一 `esc` |
| `static/js/format.js` | 137–144 | 收据 HTML 里 `url` / 判定 / `receipt_id` / `hash` / `ver` / 链信息全部转义 |
| `static/js/main.js` | 129 | 上传文件名 `f.name` 转义（攻击者可控的实验：`<img onerror>.json`） |
| `static/js/chat.js` | 5–10 | `addChatMsg` 增加"唯一受控 HTML sink"的契约注释 |
| `scripts/run_all_tests.py` | 36 | MODULES 增加 `tests.test_frontend`（15 → 16 模块） |

---

## 2. U6.1 拆分：做法与闸门

### 2.1 为什么是 classic script 而不是 ES module

原代码是**一个 `<script>` 里的 1217 行**，函数之间靠全局作用域互相调用（`showVerdict` 调 `renderChecks`，`goTab` 调 `loadLog`……），HTML 里还有 `onclick="verifyDocFromExtract()"` 这类内联调用。ES module 会引入模块作用域，等于**要求逐字重写 1200 行并重新设计全部调用关系**——那是转录风险，不是工程收益。

因此采用 **经典脚本 + 固定加载顺序**：作用域语义与原实现完全一致，函数与全局可逐字保留，内联 handler 无需 bridge。每个文件顶部保留 `"use strict";`（原先整块严格模式，拆分后逐文件生效，语义不变）。

### 2.2 切分方式：按行号机械切片，不重打一遍

`u6_map.py` 先用正则导出原 `<script>` 内**所有顶层语句的行号表**（`function` / `const` / `let` / 段注释），人工核对每个函数的起止，再让 `u6_split.py` **按行号区间机械抽取**。区间覆盖 `580–1795` 连续无缝（每个区间边界都落在"下一个声明之前"），因此**零转录误差**——每个字符都是原文件的字符。

### 2.3 拆分暴露出的真缺陷（不是拆分造成的，是拆分才照出来的）

**缺陷 1：`/static` 从来没被挂载过。**
`app/main.py` 只有 `FileResponse(STATIC_DIR / "index.html")`，**没有任何 `StaticFiles`**——因为过去页面自带 CSS 与 JS，不需要服务静态文件。拆分后若不补挂载，`/static/css/portal.css` 与 8 个 JS 全部 404，页面会变成"白底 + 无脚本"，而且**在浏览器里几乎立刻可见、在语法检查里完全不可见**。已补 `app.mount("/static", ...)`，并由 `test_css_served` / `test_each_script_served` / `test_page_still_renders` 三条测试锁死。

**缺陷 2：切分脚本漏了 `.js` 后缀。**
生成的标签是 `/static/js/core`（没有扩展名）。`node --check` 与文件存在性检查都发现不了，**只有"测试真的去 GET 每个资源"才发现**——`test_scripts_are_referenced_in_order` 和 `test_each_script_served` 同时报红。已修正（`u6_split.py` 也已同步修正，重跑不会再犯）。

**缺陷 3：`chipFor()` 被切了两次。**
原 832–839 行同时落进 `verify.js`（771–868 区间内部）与 `format.js`（832–839 单独区间）。函数重复声明不会报错（后者覆盖前者），因此**语法检查全绿、行为也对**，但它是拆分产物里的结构性冗余。已从 `verify.js` 删除，只留 `format.js` 一份。

### 2.4 拆后结构

```
static/
├─ index.html            392 行（外壳：head + link + 9 个 panel + 8 个 script）
├─ index.legacy.html    1798 行（回滚基线）
├─ css/portal.css        200 行
└─ js/ core 46 · format 198 · verify 250 · registrar 375 ·
       student 32 · log 59 · chat 115 · main 184   （合计 1102 行）
```

未拆出去的部分仍然留在外壳里：9 个面板的 HTML（约 370 行）——那是**内容**不是代码，拆出去只会让 `index.html` 变成纯索引、把模板字符串搬进 JS，反而增加注入面。

---

## 3. U6.2 XSS 审计：29 处逐处定性

统计口径：`innerHTML|outerHTML|insertAdjacentHTML|document.write`，含 1 处注释命中。**28 处真实调用 + 1 处注释**（core.js:22 是新写的说明注释，不是 sink）。

### 3.1 判定表

| # | 位置 | 数据来源 | 判定 | 处理 |
|---|---|---|---|---|
| 1 | `core.js` 注释 | — | 非 sink | 新增注释 |
| 2 | `format.js:59` 六项检查表 | 常量 `CHECK_META` + 布尔 | 安全（无外部字符串） | — |
| 3 | `format.js:75` 持有人表 | 文档字段（学生自填/PDF） | **已转义** | 保留 `esc(r[0])`/`esc(r[1])` |
| 4 | `format.js:159` `document.write` | 收据 | **收据内容此前未转义** | 修 137–144 |
| 5 | `format.js:194` 小时图表 SVG | `hour.count`（数字）+ 时间标签 | 安全 | 标签本已 `esc` |
| 6 | `verify.js:71` 批量结果 | 服务端回显的 `row` / `error` / `receipt_id` | **未转义 → 已修** | 全字段 `esc` |
| 7 | `verify.js:236` PDF 填充提示 | `warnings`（**来自 PDF 文本层**）、字段名 | **未转义 → 已修** | 逐条 `esc` |
| 8 | `verify.js:245` 填充失败提示 | `friendlyErr(e.message)`（可能回显 detail） | **未转义 → 已修** | 包 `esc` |
| 9 | `registrar.js:28` API Key 表 | `k.name`（管理员自填）/ `k.id` | **未转义 → 已修** | `esc` |
| 10 | `registrar.js:158` 批量预览 | CSV 单元格（`csvToCredentials` 整形） | 姓名等已转义，**`r.row` 未转义 → 已修** | `esc(r.row)` |
| 11 | `registrar.js:185` 批量签发结果 | `pdf_url`/`qr_url`/`hash`/`row` | **URL 与 row 未转义 → 已修** | `esc` |
| 12 | `registrar.js:269` 签发方表 | `name`/`ds_algo`/`sha256fgpt` | 已转义 | — |
| 13-14 | `registrar.js:274、41、57、22` 错误行 | `friendlyErr` / `e.message` | 已转义 | — |
| 15 | `registrar.js:329` 自制凭证结果卡 | `hashed_document`/`output_dir`/`pdf_url`/`file_id` | **未转义 → 已修** | `esc` |
| 16 | `registrar.js:364` 空列表提示 | 常量 | 安全 | — |
| 17 | `registrar.js:365` 自制凭证列表 | `f.name`/`pdf_url`/`json_url` | **未转义 → 已修** | `esc` |
| 18 | `student.js:22` 学生凭证表 | `doc_type`/`degree`/`verdict`/`hash`（URL 用 `encodeURIComponent`） | 已转义 / 已编码 | — |
| 19 | `log.js:13` 验证日志 | `hash_prefix` / `verdict_pill` | 已转义 | — |
| 20 | `log.js:19` 链尾 | `b.height`（数字）/`action`/`hash_prefix` | 数字未转义 → 统一 `esc` | `esc` |
| 21 | `log.js:31/33` 异常监控 | `method`/`signer`/`reasons`/`threshold`/`count` | 字符串已转义，数字统一 `esc` | `esc` |
| 22 | `log.js:54` 通知表 | `to`/`status`/`detail` | 已转义 | — |
| 23 | `chat.js:8` `addChatMsg` | 组合：人物卡 + 答案 + 联网卡 + 来源 | **受控 sink**：所有服务端字符串在调用方逐个 `esc`，已加契约注释 | 保留 |
| 24 | `chat.js:92` `box.innerHTML = ""` | 常量空串 | 安全 | — |
| 25 | `main.js:129` PDF 提取中的提示 | **文件名** | **未转义 → 已修**（`<img onerror>.pdf` 可注入） | `esc(f.name)` |
| 26 | `main.js:131` 状态替换 | 上一条 `innerHTML` 字符串内 `replace` | 同源，修 25 后安全 | — |
| 27 | `verify.js:79`（旧编号）| 见 #6 | 合并 | — |
| 28 | `main.js` 30 | 见 #25 | 合并 | — |
| 29 | `log.js:41/57` 错误行 | `e.message` | 已转义 | — |

### 3.2 计划要求的四类动态内容，逐一交代

| 类别 | 位置 | 结论 |
|---|---|---|
| **人物卡** | `chat.js:32-50 personCard` | 姓名/学号掩码/学位/签发方/判定全部 `esc`；`data-web` 属性同样 `esc`（属性注入路径已封） |
| **日志** | `log.js:5-59` 三张表 + 异常框 | 字符串字段均 `esc`；本轮把仍裸露的数字（height/threshold/count）也统一 `esc` |
| **来源** | `chat.js:13-23 sourceList` | `id·height·action·score` 拼成一个 tag 后整体 `esc`，`s.text` 单独 `esc` |
| **联网结果** | `chat.js:51-64 webCard` | `url` 进 `href` 前 `esc`（封掉 `"` 逃逸），`title`/`snippet`/`note` 均 `esc`；非 ok 时只显示 `reason` 且已 `esc` |

### 3.3 为什么"转义函数"要重写

原 `esc()`：建 `div`、塞 `textContent`、读回 `innerHTML`。**功能上是对的**，但它只能在浏览器里跑——于是**没有任何测试能断言 `"<img onerror=...>"` 真的被中和了**，所有前端转义都处于"看起来对、没人能证明"的状态。

改为 `escapeHtml(s)`：纯字符串、`replace(/[&<>"']/g)`、`null/undefined → ""`；`esc()` 保留为委托（公共调用点一个不改）。收益是双重的：可测试 + 只剩一个地方需要审。

附带修掉一个语义细节：旧实现在 `document.createElement` 缺失时会抛异常；新实现对 `0` / `false` 返回 `"0"` / `"false"` 而不是空串（旧实现也会这样，此处只是明确化）。

---

## 4. U6.3 前端测试

### 4.1 测试载体：一个 VM realm 顶替浏览器

`tests/frontend/harness.mjs` 用 `node:vm` 建一个 realm，注入最小假 DOM（`getElementById` 对任意 id 返回记录型元素、`createElement`、`classList`、`addEventListener`、`querySelectorAll`）、假 `fetch`（路由 stub）、`localStorage`、`location`、`navigator`，然后**按浏览器的顺序把 8 个脚本逐个 `runInContext`**。

这一步顺带成为"拆分正确性"的机器验证：
- 经典脚本同 realm 内**重复 `const` 会抛 SyntaxError**（真实浏览器同样如此）——所以拆分里若有两份同名 `const`，这里直接红；
- `main.js` 的 **40+ 处 `addEventListener` 接线与整段 boot（`refreshHealth` / `initVersion` / `loadCredSamples` / `loadSamples` / `loadSuggestions` / `loadGenHint`）都真实执行**，任何一个函数名拼错、加载顺序错、依赖缺失都会在这里抛出（首轮就抓到 `location.pathname` 未定义导致 main.js 起不来）。

### 4.2 断言覆盖（34 条）

| 组 | 内容 |
|---|---|
| 转义函数 | 完整标签 + 引号 handler、`<script>`、`&`、`'`、`null`/`undefined`、`0`、`esc` 与 `escapeHtml` 等价 |
| 判定整形 | `verdictZh` / `verdictEn` / 缺省 `—` / `chipFor` 不放过裸标签 |
| 持有人卡 | `Surname` 与 `StudentID` 注入 `<img>` / `<svg onload>` → 输出无裸标签、有实体 |
| 批量验证 | `row` / `error` / `receipt_id` 注入 → 输出无裸 `<img>` |
| 人物卡 / 联网卡 | 姓名注入、判定字段带 `" onmouseover="` 的属性逃逸、`javascript:` URL、标题注入 |
| 收据 | `hashed_document` / `receipt_id` 注入 |
| 日志三表（异步） | `/api/log`、`/api/anomalies`、`/api/notifications` 三份恶意 payload 走真实 `loadLog/loadAnomalies/loadNotifications`，检查 4 个容器的产出 |
| CSV 整形 | `parseCsv` 引号内逗号、原样保留文本；`csvToCredentials` 的 item/error 形状 |

### 4.3 变异测试：证明断言不是摆设

`tests/frontend/mutation_check.py` 把 `static/` 复制到临时目录，**只把 `renderBatch` 的一处 `esc` 还原成修复前写法**，再跑同一套断言。实测输出：

```
FAIL: renderBatch must not emit a raw <img> from row data
33/34 frontend assertions passed
exit=1
```

变异测试自身退出 0（= 套件成功察觉回归），并被 `test_suite_is_not_vacuous` 纳入常规回归。**这是本轮唯一能证明"测试有效"的证据**——34/34 全绿本身不能证明什么。

### 4.4 Python 侧 12 条（`tests/test_frontend.py`）

外壳结构（无内联脚本体 / 8 个 `src` 且顺序固定 / 有 css link 且无 `<style>` / 外壳 < 旧文件 1/3）、资产存在且非空、CSS 保留关键规则、`/static/css` 与 8 个 `/static/js` 经 TestClient 200 且 MIME 正确、首页仍带 `main.js` 且不再出现 `innerHTML`、`node --check` 全通过、转义套件通过、套件非空转。

Node 找不到时 `skipTest` 并打印原因——**不会静默算过**。

---

## 5. 验证证据

### 5.1 静态与语法

| 项 | 结果 |
|---|---|
| `node --check` 8 个 JS | 全部 exit 0 |
| `ruff check app` | 4 条既有基线（`anomaly.py:71 B905`、`anomaly.py:129 B007`、`pdf_extractor.py:190 B007`、`rag_indexer.py:318 B905`），**未新增** |
| `ruff check tests` | All checks passed（新增文件中 3 条 UP020 + 1 条 F401 已用 `--select` 安全修复） |
| `mypy app` | 15 错误 / 6 文件 / 34 源文件（**与 U5.3 完全一致**，`StaticFiles` 导入未引入新错误） |

### 5.2 测试

| 项 | 结果 |
|---|---|
| `tests.test_frontend` | 12 tests OK（含变异测试） |
| 全量 JSON 后端 | **16/16 模块 green**，202 条 |
| 全量 SQLite 后端 | **16/16 模块 green**，202 条 |

逐模块：test_api 16、test_chain_integrity 10、test_custom 8、test_disclosure 16、test_employer_pack 9、test_extra2 18、test_features 8、**test_frontend 12**、test_hardening 7、test_issue_batch 5、test_pdf_extract 6、test_person 24、test_property_crypto 23、test_public_mode 6、test_rag 32、test_restart_persistence 2。

### 5.3 真实服务（非 TestClient）

`uvicorn app.main:app --port 8021` 实跑：

```
index=200 bytes=17982
css=200 type=text/css; charset=utf-8 bytes=14071
core.js=200 1555 · format.js=200 9838 · verify.js=200 10568 · registrar.js=200 17198
student.js=200 1722 · log.js=200 2752 · chat.js=200 5163 · main.js=200 8459
version=200 {"app":"Gef26 credential verification portal","version":"6.0.0",
             "chain":{"name":"Gef26-credential-chain","height":11,"signers":4}}
```

### 5.4 Dockerfile

`Dockerfile` 第 11 行已有 `COPY static ./static`——**整目录复制，拆分后的 `css/` 与 `js/` 自动进镜像，无需改动**。`StaticFiles(directory=STATIC_DIR)` 在容器内解析为 `/app/static`，与 `COPY` 目标一致；静态路径无版本前缀、无 build 步骤、无 CDN 依赖，因此**不存在"构建产物与源码不同步"这类问题**（本来也没有构建）。

---

## 6. TODO 全库扫描（`app/`）

| 位置 | 内容 | 状态 |
|---|---|---|
| `rate_limit.py:50` | `TODO[external-redis]`：多 worker 需跨进程计数器 | 既有，未解决 |
| `session_store.py:69` | `TODO[external-redis]`：会话跨进程共享 | U5.3 新增，未解决 |
| `blockchain_util.py:3/13/248` | 引用 `TODO.md` / `JSONSTRUCTURE.md` 文件名，非标记 | 不计 |

（`session_store.py:11` 为 docstring 内提及同一 TODO 的说明行。）本轮**未新增、未改动任何 TODO**。

---

## 7. 未覆盖与已知边界（写明，不粉饰）

1. **无浏览器 E2E**。计划明确"不要求浏览器 E2E"，本轮以 VM realm + 真实 HTTP 取代。**视觉与交互（标签切换动画、拖拽高亮、打印窗口）未在真实浏览器中确认**；VM 里 `document.write`、`window.open`、剪贴板均为 stub。
2. **`innerHTML` 仍是主要写入方式**，只是数据全部先转义。没有改成 `textContent` + 逐节点构造——那需要重写 28 个渲染函数的版式逻辑，等于把前端重做一遍；本轮的边界是"**消灭未转义拼接**"，不是"消灭 `innerHTML`"。计划原文允许"仅允许白名单 HTML 片段走受控渲染"，本轮的受控点是 `escapeHtml` 与 `addChatMsg` 契约。
3. **`chat.js:8 addChatMsg` 仍是"信任调用方已转义"的接口**。已加注释说明契约，但没有运行时校验（例如传入白名单校验）。若未来有人直接 `addChatMsg(res.something)`，注释挡不住。
4. **无 CSP / 无 SRI / 无 `X-Content-Type-Options` 之外的响应头加固**。真正的纵深防御需要 `Content-Security-Policy: script-src 'self'`（本项目无内联脚本，**拆分后恰好具备加 CSP 的条件**），但本轮未做——前端仍有 `onclick="verifyDocFromExtract()"` 等内联属性（拆分时就说明它们是保留全局函数的原因），加 CSP 需先把这些属性改成 `addEventListener`，属独立一批。
5. **`static/index.legacy.html` 会随镜像发布**。它是计划要求的回滚基线，但 Dockerfile 的 `COPY static ./static` 会把它一起打包，等于对外暴露一份**完全相同的旧页面**（内容无敏感信息，代价是体积与"两个可访问入口"的困惑）。若在意应在 `.dockerignore` 排除，或把基线移出 `static/`。
6. **`document.write` 仍在**（打印窗口）。目标窗口是 `window.open("", "_blank")` 得到的空白自有窗口，内容已转义，因此判定为可接受；换成 `document.createElement` + `appendChild` 会破坏"边生成边打印"的既有行为。
7. **数值也做了 `esc`**（height / threshold / count）。这是防御性冗余，会让纯数字经过一次正则替换；不影响正确性，但**不是"因为发现漏洞"才改的**，属统一口径。
8. **`u6_split.py` 不可直接重跑**：它读的是已拆分的 `index.html`。若需重切，必须先 `Copy-Item static\index.legacy.html static\index.html`（脚本已补 `.js` 后缀修正）。
9. **前端仍未跟 U3–U5 的新能力**（`generation.degraded` / `validation_ok` / `sources_are_fallback` 无渲染入口，`/api/admin/chain-snapshot`、`/api/disclose`、角色令牌体系无 UI）。U6 拆完只是**具备了接这些入口的结构**，接线是后续工作。

---

## 8. 回滚方式

前端整体回滚：

```
Copy-Item static\index.legacy.html static\index.html
Remove-Item -Recurse static\js, static\css
```

并把 `app/main.py` 的 `app.mount("/static", ...)` 与 `StaticFiles` 导入删除（回滚后不再需要静态挂载；留着也无害，只是多一个指向空目录的挂载点）。

`tests.test_frontend` 会在回滚后失败（它断言的是拆分后的结构）——这是**预期**，回滚时同时删掉该模块与 `tests/frontend/`，并把 `run_all_tests.py` 的 MODULES 恢复到 15 项。

---

## 9. 下一批次

U7（测试深度与可观测性）：Fuzz（PDF 解析 / JSON 形状 / 哈希格式 / 批量输入）、损坏链注入、并发签发撤销一致性、测试分层标记；请求 ID 中间件、结构化日志（不含 PII / 完整哈希）、指标端点、`/healthz` 依赖细化；压测脚本。
