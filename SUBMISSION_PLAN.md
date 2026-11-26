# QuantumGuard / GEF Mobile — 收尾交付详细计划

> 依据：本地源码实测（108 测试 / 12 模块）、任务台账 #37–#43、课程提交要求截图、在线 deck 当前状态。
> 目标：完成三条提交线（Learning Summary DOCX、在线 PPT deck、A0 海报 PPTX），打通前置素材（GitHub 仓库、YouTube 视频、队员分工），并把代码质量补强列为提交后的可选批次。

---

## 0. 范围与原则

- **在范围内**：提交材料收尾、素材补齐、文档与演示口径对齐、交付物命名与终检。
- **不在本次范围**：新增产品功能、生产级重构（数据库/鉴权/前端框架）；这些进入第 7 节可选批次。
- **口径冻结**：提交件一律使用当前代码事实——链哈希 `sha3_512`（JCS 规范化）；签名 ML-DSA-65 / RSA-PSS-2048 / ec.secp256r1；108 个测试 / 12 模块；六项检查；项目标题 `QuantumGuard / GEF Mobile — A Post-Quantum Credential Verification Portal`。旧原型口径（RSA-2048/SHA-256/Ed25519/20 测试/Merkle 累加器/P2P）不得出现。

---

## 1. 现状盘点

### 1.1 已完成（有产物证据）

| 项 | 状态 | 证据 |
|---|---|---|
| 门户后端 + 前端 | 完成，本地可运行 | `verification-portal/app/` 20 模块；`static/index.html` |
| 自动化测试 | 108 用例 / 12 模块 | `tests/`，逐模块计数已核对 |
| 本地 git 初始化 | 2 次提交 | `8356e80` Initial commit；`11e7994` GitHub push guide；远程未建未推 |
| 演示视频（本地） | 67.5s，1280×720，英文旁白，5 镜头 | `demo-media/GEF-mobile-demo.mp4` |
| 海报位图 v1/v2 | 已有两张 PNG | `demo-media/poster-海报.png`、`poster-海报-v2.png` |
| Summary 草稿 | 英文 12 节 + 14 条参考，占位符未填 | `Learning_Summary_draft.md` / `.docx` |
| 在线 deck | 2/12 页已写入 | 封面 `pyy`、TL;DR `pys`；ID `G6o4sZnxTlBhXWdIHerc6gxWnnt` |
| 代码逻辑详解 | 已交付 | `CODE_WALKTHROUGH.md`（逐模块/函数，含答辩口径） |
| 截图素材 | 9 张已上传 deck，token 已备 | `slides_work_v2/tokens.json` |

### 1.2 进行中 / 未开始

| 任务 | 台账 | 状态 | 缺口 |
|---|---|---|---|
| Learning Summary 定稿 | #40 | 进行中 | 7 类占位符；链接未填；未套模板导出终稿 |
| PPT deck 重做 | #41 | 进行中 | 第 3–12 页 XML 未写、未写入 |
| A0 海报 PPTX | #42 | 未开始 | 无模板；无两个 QR；未建 PPTX |
| 收集 YouTube 链接 | #39 | 阻塞 | 视频未达 3–5 分钟、每人讲解要求；未上传 |
| GitHub 链接 | — | 阻塞 | 远程仓库未创建、未推送 |

### 1.3 已核实的环境事实

- 本地环境 Windows，项目根 `C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project`。
- 课件包 zip 内**没有** `Template_Poster.pptx`；Downloads 也未找到该模板。
- Summary 模板 `Template_Learning_Summary.docx` 已解析：US letter 单栏 Times New Roman，最多 4 页；页眉页脚不可改；URL 用 Regular 字体完整打出；参考文献 8pt 悬挂缩进。
- 海报要求（截图）：A0 841×1189mm；四边 ≥10mm 留白；单页单面；文件名 `{ProjectID}_Poster.pptx`；两个二维码（YouTube 演示视频 + GitHub 源码）；PPT 格式；视频 ≥720p、3–5 分钟、每名学生展示自己负责的源码部分并解释逻辑功能。

---

## 2. 阻塞输入清单（必须人工提供，计划启动前先收齐）

| # | 输入项 | 用途 | 影响交付物 | 当前状态 | 备注 |
|---|---|---|---|---|---|
| B1 | Project ID（如 `P01`） | 三个文件命名、标题页、海报 | Summary / PPT / 海报 | 缺 | 文件名 `{ProjectID}_Learning_Summary.docx`、`{ProjectID}_Poster.pptx` |
| B2 | 队员真实姓名（1–3 人） | 作者署名、个人贡献、视频分段 | Summary / PPT / 海报 | 缺 | 与课程注册表一致 |
| B3 | 单位 / 学校 / 联系邮箱 | Summary 作者块 | Summary | 缺 | 模板要求 9pt 斜体单位、9pt Courier 邮箱 |
| B4 | 每人分工文案（负责模块 + 学到什么） | Summary 第 11 节反思；视频讲稿；答辩口径 | Summary / 视频 / PPT | 缺 | 可对照 `CODE_WALKTHROUGH.md` 模块表认领 |
| B5 | YouTube 视频链接 | Summary 资源链接；海报 YouTube 二维码 | Summary / 海报 | 缺 | 需先完成 Phase 2 视频达标再上传 |
| B6 | GitHub 仓库链接（Public/Private + 账号） | Summary 资源链接；海报 GitHub 二维码；PPT 源码引用 | Summary / PPT / 海报 | 缺 | 需先完成 Phase 1 推送 |
| B7 | 海报模板 `Template_Poster.pptx`（若课程强制） | 海报版式基线 | 海报 | 缺 | 本地与课件包均无；需向课程组索取，否则按截图要求自设计 |
| B8 | 各交付物最终截止日期确认 | 排期 | 全部 | 待确认 | 截图显示海报截止 06 Nov 23:59（系统日期 13 Nov，已过，以课程最新通知为准）；Summary 截止 15 Nov（周日） |

> 规则：B1–B4 不依赖任何代码，可并行收集；B5/B6 是关键路径上的交付物链接，必须在 Summary 与海报定稿前落地。

---

## 3. 依赖关系（关键路径）

```
B2/B4 分工 ──────────────┐
                         ├─→ 视频分段脚本 ─→ Phase 2 重录 ─→ YouTube 链接(B5) ─┐
B1 Project ID ──────────┤                                                  ├─→ 海报两个 QR
B6 远程仓库 ─→ Phase 1 推送 ─→ GitHub 链接(B6) ─────────────────────────────┘
B3 单位/邮箱 ─→ Phase 3 Summary 定稿 ──────────────────────────────────────→ 提交
CODE_WALKTHROUGH.md ─→ 视频讲稿 / PPT 备注 / 答辩口径
```

- **关键路径**：分工确认 → GitHub 推送 → 视频重录上传 → 海报 QR 与 Summary 链接回填。
- **可并行**：PPT 第 3–12 页撰写（不依赖外部链接，链接留占位后回填）；Summary 正文事实复核；海报版式初稿。

---

## 4. 工作流分解

### Phase 1 — 仓库基线与 GitHub 推送（前置，无外部依赖可先做）

| 任务 | 步骤 | 产物 | 验收标准 | 依赖 | 风险 / 缓解 | 回滚 |
|---|---|---|---|---|---|---|
| 1.1 核对本地 git 状态 | 检查未跟踪/已修改文件；决定 `CODE_WALKTHROUGH.md`、`slides_work_v2/`、草稿 docx 入库还是忽略；确认 `.gitignore` 覆盖 `.venv/`、`data/`、`__pycache__/`、中间视频 | 干净的暂存区 | 无敏感密钥入库；`data/` 演示链不入库 | — | 误提交大文件 → 先核对 `.gitignore` 再 add | 撤销暂存，不提交 |
| 1.2 全量测试留痕 | 用 venv Python 跑 `scripts/run_all_tests.py`（或 pytest 全量） | 测试结果记录 | 108 用例全绿；与提交口径一致 | 1.1 | 环境缺依赖 → 按 `requirements.txt` 安装；失败先修再提交 | 不阻断文档工作，但提交件不得写"全绿" |
| 1.3 创建远程仓库并推送 | 按 `GITHUB_SETUP.md`：建仓 → 配 remote → 确认提交身份 → push；Public 或 Private 按课程要求 | GitHub 仓库 URL（B6） | 克隆可见源码；README、requirements、测试目录齐全；无 `.venv`/`data/` 进入远程 | 1.1, 1.2 | 身份占位邮箱 → 推送前 amend 为队员邮箱；私有仓库评委不可见 → 确认课程要求 | 远程仓可删除重建 |
| 1.4 链接回填准备 | 记录仓库 URL、默认分支、最近提交哈希 | 链接卡片 | Summary/PPT/海报可直接引用 | 1.3 | — | — |

### Phase 2 — 演示视频达标（关键路径，依赖分工 B4）

**现状差距**：本地 67.5s 旁白不满足"3–5 分钟、每名学生展示自己负责的源码部分并解释逻辑功能"。

| 任务 | 步骤 | 产物 | 验收标准 | 依赖 | 风险 / 缓解 | 回滚 |
|---|---|---|---|---|---|---|
| 2.1 分段脚本 | 按认领模块切分讲稿；每人两段式："功能一句 + 逻辑一句"；结构对照 `CODE_WALKTHROUGH.md` 第 18 节；保留现有 5 镜头作为系统演示段 | 视频脚本（分镜表：时间码 / 讲解人 / 对应源码文件 / 口播要点） | 每名队员都有对应源码讲解段；时长目标 3–5 分钟；技术口径与冻结口径一致 | B4, CODE_WALKTHROUGH.md | 队员异地 → 各自录屏 + 旁白，后期拼接；讲稿过长 → 每模块控制 30–60s | 先用现有 67.5s 版本占位，标注"待补每人讲解段" |
| 2.2 录制 / 补录 | 系统演示沿用现有镜头；各人录自己负责模块的代码画面 + 讲解；必要时补链核心、RAG、PDF 模块特写 | 分段素材 | 画面可读代码；口播能说清"输入 → 处理 → 输出" | 2.1 | 口齿/紧张 → 照讲稿念；杂音 → 后期配旁白 | 素材可重录，不影响本地代码 |
| 2.3 剪辑导出 | 拼接、加字幕/章节、统一片头片尾；导出 ≥720p | 终版视频文件 | 时长 3–5 min；无黑屏/断音；文件名含项目 ID | 2.2 | 体积过大 → 1080p 30fps、H.264 | 保留旧版 `GEF-mobile-demo.mp4` |
| 2.4 上传 YouTube | 按课程要求设可见性；取分享链接（B5） | YouTube URL | 链接可打开；标题/简介含项目 ID 与队员；二维码可扫码直达 | 2.3 | 地区限制 → 确认账号地区；未公开 → 评委无法访问 | 改可见性或重传 |

### Phase 3 — Learning Summary 定稿（依赖 B1/B2/B3/B5/B6）

| 任务 | 步骤 | 产物 | 验收标准 | 依赖 | 风险 / 缓解 | 回滚 |
|---|---|---|---|---|---|---|
| 3.1 填占位符 | 把 B1/B2/B3/B5/B6/B4 填入 `Learning_Summary_draft.md`；个人反思按人撰写 | 终稿 Markdown | 无残留 `[ ... ]` 占位；链接完整写出（Regular 字体要求在 DOCX 层保证） | 2, 4 | 链接迟到 → 先留显式占位，定稿前回填 | 草稿可恢复 |
| 3.2 事实复核 | 逐项核对：六项检查、108/12、技术栈表、AI 组件、局限章节；删除与代码不符的表述 | 复核清单 | 每个数字/算法名能在源码或测试计数中找到依据 | 1.2 | 旧口径残留 → 对照第 0 节冻结口径扫描 | — |
| 3.3 生成终稿 DOCX | 改 `slides_work_v2/build_summary.py` 指向终稿内容；以课程模板副本为底覆写槽位、删样例、插正文与 14 条参考；运行脚本输出 | `{ProjectID}_Learning_Summary.docx` | 模板字体/字号/缩进未被破坏；页眉页脚原样保留 | 3.1, 3.2 | 脚本串格式 → 先在副本上改；中文乱码 → UTF-8 无 BOM 落盘 | 草稿 docx 保留可重跑 |
| 3.4 排版终检 | 页数 ≤4；摘要、正文、参考文献层级正确；URL 完整无超链接样式；参考文献悬挂缩进；无样例表格/插图残留 | 终检记录 | 对照模板解析维度（d0/d1/d2/d3/d4/d9）逐项通过 | 3.3 | 超 4 页 → 压缩个人反思与局限表述，不动参考文献 | 回退上一版 docx |
| 3.5 命名归档 | 按 `{ProjectID}_Learning_Summary.docx` 重命名，放入项目交付目录 | 提交件 | 文件名与课程要求逐字一致 | B1, 3.4 | — | — |

### Phase 4 — PPT deck 完成（12 页；已完成 1–2，链接可后回填）

**已备素材**：9 张截图 token 见附录 A；设计系统：白底、藏青标题 `rgba(0,28,84,1)`、强调蓝 `rgba(0,112,186,1)`、正文石板灰 `rgba(71,85,105,1)`；正文微软雅黑，编号/哈希 Roboto Mono。

| 页码 | 标题（判断句） | 核心内容 | 素材 | 备注要求 |
|---|---|---|---|---|
| 3 | 问题与目标 / 范围边界 | 集中式核验慢/贵/脆；量子 harvest-now-forge-later 风险；本项目边界：单节点私有链，不做共识 | 图标 | 讲清"不做什么" |
| 4 | 系统架构 | 三层：门户 API → 服务/链核心 → 链与链外索引；模块名映射 | 架构示意（原生形状/SVG） | 对应 README 架构图 |
| 5 | 数据模型与密码学 | 三段凭证结构；JCS → SHA3-512 → Merkle 根；ML-DSA-65/RSA-PSS/ECDSA；SPKI 指纹 | 哈希/签名流程示意 | 课程映射 P2L3/P2L4/P2L5 |
| 6 | 六项检查 | 链完整性 / 签发方可信 / 链上记录 / 哈希匹配 / 签名有效 / 未撤销；哈希-only 查询的判定差异 | 编号卡片 | 每项一句"怎么算" |
| 7 | 门户演示流程 | 落地页 → VALID 样例 → 撤销/篡改样例 → 签发 → 公开日志 | verify / revoked / tampered / issue / log 五张截图 | 4:3 保持比例 |
| 8 | 按角色功能包 | 核验者/雇主：批量核验、API Key、状态列表、收据；持证人：学生查询、QR；注册处：批量签发、撤销原因/生效日 | signers / qr 截图 | 表格或三栏 |
| 9 | AI / GenAI 层 | 精确 ID 优先 → MiniLM-L6-v2 + FAISS 检索 → 三级生成器回退；脱敏人物卡；隐私联网；引用来源 | chat 截图 | 课程映射 GenAI/RAG |
| 10 | 测试与加固 | 108/12 模块分布；限流、体积/深度防护、损坏链结构化判定、原子写、重启持久化 | 测试计数表 | 诚实标注演示规模 |
| 11 | 威胁模型与局限 | 单节点链、演示私钥、仅支持门户签发 PDF、链外明文索引、联网依赖、VALID 非法律认证 | 对照表 | 主动承认局限 |
| 12 | 后续工作与交付物 | 可选：数据库替换、真实试点、扫描件 OCR；交付物：视频 QR、源码链接、文档 | 链接占位（回填 B5/B6） | 收尾页 |

| 任务 | 步骤 | 验收标准 | 依赖 |
|---|---|---|---|
| 4.1 逐页落 XML | 按 ppt 技能流程：每页先写本地 XML → `+add-slide --no-lint` → 确认 `.ok==true` 且 `slide_id` 非空 → 记录页码与 ID；禁止批量写页 | 12 页全部落库；页序正确；截图 token 直写 `<img src>` | 附录 A token |
| 4.2 讲稿备注 | 每页 `<note>` 写 3–5 句可照读讲稿 | 与 Summary/视频口径一致 | 4.1 |
| 4.3 链接回填 | 第 12 页（及需要处）回填 YouTube / GitHub 链接 | 链接与 B5/B6 一致 | B5, B6 |
| 4.4 终检 | 无 emoji；图标走 IconPark；文字无溢出；配色字体统一 | 与前两页风格连续 | 4.1–4.3 |

### Phase 5 — A0 海报 PPTX（依赖 B1/B2/B5/B6/B7）

| 任务 | 步骤 | 产物 | 验收标准 | 依赖 | 风险 / 缓解 | 回滚 |
|---|---|---|---|---|---|---|
| 5.1 模板确认 | 先确认是否拿到 `Template_Poster.pptx`（B7）；无模板则按截图自设计 | 版式基线 | 若有模板，不改动其页眉页脚与网格 | B7 | 模板迟到 → 先做自设计草稿，拿到模板再套 | 草稿保留 |
| 5.2 画布规格 | A0 竖版 841×1189mm；四边 ≥10mm 安全留白；单页单面 | PPTX 画布 | 尺寸与边距达标；内容不出血到留白外 | — | PPT 页面单位按毫米设置；导出前核对页面设置 | — |
| 5.3 内容排版 | 主标题 + 一句话问题；方案与三角色；技术栈区块；六项检查速览；AI 层一句话；项目 ID + 队员署名；两个 QR 及标注 | 海报版面 | 技术栈可辨识：ML-DSA-65 后量子签名、RSA-PSS/ECDSA 兼容、SHA3-512 + JCS、Merkle 根、FastAPI、MiniLM-L6-v2 + FAISS、IsolationForest、reportlab/pypdf | B2, 冻结口径 | 信息过挤 → 分层：主视觉 / 技术条 / 检查条 / QR 区 | 精简区块 |
| 5.4 二维码 | 生成 YouTube QR（B5）与 GitHub QR（B6）；扫码直达；旁边标注链接用途 | 两枚可扫 QR | 手机扫码可打开；QR 不被裁切/变形 | B5, B6 | 链接迟到 → QR 占位框标注，定稿前替换 | 占位可换 |
| 5.5 命名导出 | `{ProjectID}_Poster.pptx`，PPT 格式 | 提交件 | 文件名逐字一致；单页；可在 PowerPoint/WPS 打开 | B1, 5.2–5.4 | — | — |

### Phase 6 — 终检与打包

| 任务 | 验收标准 |
|---|---|
| 6.1 链接互校 | Summary、PPT、海报中的 YouTube / GitHub 链接一致且可打开；两个 QR 扫码结果与链接一致 |
| 6.2 占位符扫描 | 三份材料全文无 `[PROJECT ID]`、`[Name]`、`[LINK ...]` 等残留 |
| 6.3 命名核对 | 文件名符合课程格式；扩展名正确（.docx / .pptx） |
| 6.4 口径一致性 | 测试数、算法名、检查项、项目标题三处一致；无旧原型口径 |
| 6.5 提交清单 | 按课程要求逐项上传；保留本地副本 |

---

## 5. 排期建议

| 阶段 | 前置 | 预估（专注工作时间） | 可否并行 |
|---|---|---|---|
| Phase 1 仓库推送 | 无 | 0.5 天 | 先做，解锁 B6 |
| Phase 2 视频达标 | 分工 B4 | 0.5–1 天（含异地录制协调） | 与 Phase 3/4 文本工作部分并行 |
| Phase 3 Summary 定稿 | B1/B2/B3/B5/B6 | 0.5 天 | 正文复核可先行，链接回填最后 |
| Phase 4 PPT 3–12 页 | 截图 token（已备） | 0.5–1 天 | 与 Phase 3 并行 |
| Phase 5 海报 | B1/B2/B5/B6/B7 | 0.5 天 | 版式可先行，QR 最后贴 |
| Phase 6 终检 | 以上全部 | 0.25 天 | — |

**关键路径**：B4 分工 → Phase 1 推送 → Phase 2 视频上传 → Phase 5/3 链接回填。建议顺序：先 1.1–1.3 推仓库，同时收 B1–B4；再做 PPT 与 Summary 正文；视频和 QR 链接最后回填。

---

## 6. 风险登记

| 风险 | 影响 | 缓解 | 回滚 / 兜底 |
|---|---|---|---|
| 队员信息/分工收不齐 | Summary 作者块、视频分段、海报署名卡住 | 先按占位排版；第 2 节清单逐项追 | 提交前以课程注册表为准补填 |
| 视频无法达到 3–5 分钟每人讲解 | 海报 QR 与 Summary 链接不合规 | 脚本先行；异地录屏拼接；先传旧版占位 | 标注待补，最终版替换 |
| GitHub 仓库设为 Private | 评委无法访问源码 QR | 确认课程要求；需要公开则推送 Public 仓 | 另开 Public 镜像仓 |
| 海报模板未提供 | 版式基线缺失 | 按截图 A0 规格自设计；索取模板后再套 | 自设计版本可独立提交 |
| 截止日期已过（海报截图 06 Nov） | 提交有效性风险 | 以课程最新通知为准；立即优先完成海报与 Summary | — |
| 提交件口径与代码不符 | 答辩被追问失分 | 第 3.2/6.4 节双重复核；数字以测试计数和源码为准 | — |
| 远程推送暴露密钥/数据 | 安全事故 | 推送前扫描 `data/`、`.venv/`、硬编码密钥；`.gitignore` 核对 | 立即轮换任何入库凭证 |

---

## 7. 可选代码质量补强（提交后批次，不阻塞交付）

> 依据第 1 节实测：类型标注 53/190；19 处宽异常；无 lint/类型检查/CI；JSON 文件存储；单文件 1730 行前端；27 处 `innerHTML` 赋值。提交前不做，避免扰动已绿的测试口径。

| 批次 | 内容 | 现状证据 | 验收标准 |
|---|---|---|---|
| Q1 工程规范 | 引入 ruff + mypy（先严格卡 crypto/chain 两模块）；`tests/conftest.py` 抽隔离链夹具；requirements 锁版本；补最小 CI 跑测试 | 无 pyproject/setup.cfg/CI/conftest | 静态检查通过；测试仍 108 全绿 |
| Q2 异常与日志 | 收窄 19 处 `except Exception` 到具体类型；关键路径接结构化日志；去掉 CLI 辅助函数外的 `print` | 宽异常 19；`print` 3 处（CLI 辅助） | 无吞错返回空列表的路径；日志可追溯 |
| Q3 持久化 | 服务层接口不动，JSON 文件存储替换为 SQLite（SQLModel）；限流在多 Worker 下可共享 | 链/收据/Key/日志均为磁盘 JSON | 重启持久化测试通过；链核心接口签名不变 |
| Q4 鉴权 | 会话/JWT + RBAC；Key 轮换与过期；审计日志导出 | 管理端仅共享静态 token | 管理端点不能仅凭静态头访问；Key 可吊销轮换 |
| Q5 前端 | `innerHTML` 转义审计；按标签页拆 JS/CSS 文件；补前端最小测试 | 单 HTML 1730 行；27 处 innerHTML | 无未转义拼接；页面功能回归通过 |
| Q6 测试深度 | 解析器 fuzz；哈希确定性 property test；检索评测集 | 以正常路径 + 防护用例为主 | 新增用例不破坏现有 108 条 |

---

## 8. 提交前总 Checklist

- [ ] B1–B8 输入全部收齐并回填
- [ ] GitHub 仓库可公开访问，链接记录在案
- [ ] YouTube 视频 ≥720p、3–5 分钟、含每人源码讲解段，链接可打开
- [ ] `{ProjectID}_Learning_Summary.docx`：≤4 页、模板格式保留、14 条参考、无占位符、链接完整
- [ ] PPT 12 页全部写入，备注讲稿齐全，链接回填
- [ ] `{ProjectID}_Poster.pptx`：A0 竖版、四边留白、单页、两枚 QR 可扫
- [ ] 三份材料口径一致：108 测试 / 12 模块、六项检查、技术栈、项目标题
- [ ] 无旧原型口径（RSA-2048/SHA-256/Ed25519/20 测试/P2P）
- [ ] 提交目录仅含最终交付件，中间脚本/草稿单独存放

---

## 附录 A — 截图 file_token 映射（PPT 直写）

| 用途 | token |
|---|---|
| verify 判定 | `Q4LTb3M9Dow38TxKenGcBErbnVg` |
| revoked 撤销 | `LEejbEuj1o1d5uxxH02cV40jnxg` |
| tampered 篡改 | `F2RQbW8r0of8bcxzhGncWNcJng` |
| issue 签发 | `Ucx4bkMBCoPWppx9BQPc4ogVnbg` |
| log 公开日志 | `GaVdbNyy0o1nNTxLskAcRxRWnwg` |
| chat AI 问答 | `SW2ebCVwpoE6xFx4E1sctQ0lnCh` |
| student 学生页 | `F3E6b1KXwoSYjCxOpzWcGcgwngb` |
| qr 二维码 | `TnMzbiQP6oewhcxu9IYcZlwfnke` |
| signers 签发方 | `XP2yb1nHVooxwUxqvVBcHc79nQg` |

## 附录 B — Summary 占位符清单（待回填）

`[PROJECT ID]`、`[Name 1/2/3]`、`[School / Institute, Hong Kong, China]`、`[email@example.com]`、`[LINK PROVIDED BY TEAMMATE]`（YouTube）、`[LINK AFTER GITHUB PUSH]`（GitHub）、三人个人贡献方括号说明。

## 附录 C — 关键路径文件

- 代码详解：`CODE_WALKTHROUGH.md`
- Summary 草稿：`Learning_Summary_draft.md` / `Learning_Summary_draft.docx`；生成脚本 `slides_work_v2/build_summary.py`
- 在线 deck：`https://my.feishu.cn/slides/G6o4sZnxTlBhXWdIHerc6gxWnnt`
- 推送步骤：`GITHUB_SETUP.md`
