# U12 — 角色与入口分离：激进方案（Radical）

> 状态：**R0–R6 已实施（2026-11-20）**；R6 完成文档对齐、三入口截图与演示视频重制（`demo.mp4` 已按 U12 顺序重排，旧的带旁白版本保留为 `demo-media/GEF-mobile-demo-preU12-narrated.mp4`）。与 `U11_role_ux_plan.md` 是替代关系，不是叠加。
> U11 的思路是「藏起来 + 拦住」；U12 的思路是**把能力从访客那一侧移除**，让越权在结构上不可能，而不是靠判断分支。

## 0. 已实施结果

| 项 | 做法 | 实测 |
|---|---|---|
| R0 静态白名单 | 只挂 `/static/css` 与 `/static/js`；`index.legacy.html` 移出 `static/` 到 `baseline/` | `/static/index.html` 404、`/static/index.legacy.html` 404、`/static/staff.html` 404、`/static/css/portal.css` 200 |
| R1 页面分离 | `index.html` 裁为公开页（5 tab、无签发/注销/签发方/API key 面板、不加载 `registrar.js`）；新增 `static/staff.html` 承载完整教职员功能 | 公开页 229 行（原 393）；公开页 `panel-issue` 命中 0；`/staff` 未配 token → 404 |
| R2 会话登录 | `GET/POST /staff/login` + `POST /staff/logout`；`/staff` 无会话时 303 到登录页；token 换 HttpOnly `staff_sid` cookie；全部 `require_roles` 依赖同时接受 header 或会话 | 真实服务实测：`/staff` 303 → `/staff/login` 200 → POST 200 `{"ok":true,"role":"admin"}` → 带会话 `/staff` 200 且含 `panel-issue` → `/api/admin/audit` 200 |
| R3 能力链接 | 新增 `app/capability.py`（HMAC-SHA256、payload 内带 `exp`）；`/me/<cap>` 持证人页、`/api/me/<cap>` 只回一份凭证；`/api/holder-link` 教职员签发链接；删除 `/api/student/{id}?dob=` | 伪造/改签/过期/不存在的凭证一律 404；有效链接 `/api/me/<cap>` 返回且仅返回 1 条；`/api/student/22000000?dob=…` 404；签发接口无 token 401 |
| R5 打包卫生 | 每份凭证在旁边写一条**无 PII** 的 `holder_index/` 行（学号、哈希、类型、学位）；持证人/学生查询改读索引，`rawjsondocs/` 退为 RAG 与 PDF 的内部副本；`build_package.py` 排除整个 `data/`，打包后扫描成品 zip | 160 文件 / 13.1 MB；扫描结果「no rawjsondocs, no PII keys, no secret-looking files」；把 zip 解到空目录后首次启动：`/` 200、签发 200、按哈希验证 200、mint 200、`/api/me` 200 一条、`/me` 页 200、篡改 404 |
| R4 通知 worker | 收件人改为部署配置 `NOTIFY_TO`，请求体里的 `student_email` 一律忽略；签发只入队，lifespan 起一个守护线程消费；同哈希只通知一次；每小时封顶 `NOTIFY_PER_HOUR`；前端删掉邮箱输入框 | 带 `student_email` 签发 → status `queued`、detail 标 `ignored`、记录 `to` 不是该地址；同凭证第二次 → `duplicate`；`drain()` 后通知落库；未配 `NOTIFY_TO` → `logged` 不发信 |
| 回归 | 全量套件 | 27/27 模块全绿；`test_frontend` 22 项、`test_extra2` 24 项（含 PII-free 索引、`rawjsondocs` 缺席仍可查、通知队列语义） |
| R6 文档与素材对齐 | README 重写（三入口表、端点表、持证人链接、通知 worker、curl、环境变量、双索引）；用真实服务重截三入口截图；`build_demo_video.py` 改为按 U12 顺序拼接（12 段 / 120 秒）并修 Windows 字体与裁切 | 8013 端口实测 `/` 200、`/staff/login` 200、`/me/<cap>` 200；截图落 `docs/screenshot-u12-{public,holder,staff-login}.png`；`demo.mp4` 7.1 MB / 120 s；`test_frontend` 22 项、全量 27/27 仍绿 |

**R2 的 CSRF 取舍（与计划有偏差，需明示）**：没有实现「双提交 token」，而是用 **`SameSite=strict` cookie + 项目已有的 Origin 白名单中间件**（`main.py:203-208`，对非 GET 请求校验 `Origin`）。两者叠加已覆盖浏览器跨站携带场景，且改造面小、不碰 8 个端点签名。若将来要防同站子域攻击，再补双提交。

**R6 期间修掉的三处真实缺陷（都不是新功能，是拆分暴露出来的）**：

1. **公开页 JS 整段崩掉**。`main.js` 直接 `$("goRegistrar").addEventListener(...)`、`$("issueBtn").addEventListener(...)`，而 R1 之后这些元素只存在于 `staff.html`；一个 `null` 抛出后，同文件后面的绑定和 `boot`（`refreshHealth`、`initVersion`、样例加载）全部不执行。症状是头部永远停在 `connecting…`、统计四项都是 `—`、样例按钮点了没反应。staff 页元素齐全，所以拆分后没人发现。修法：新增 `on(id, ev, fn)`，元素不存在就直接返回；对只存在于 `registrar.js` 的处理函数，允许传函数名字符串，点击时才解析，避免在「公开页根本没加载该脚本」时提前触发 `ReferenceError`。`format.js` 的 `issueQrBtn` 同类问题一并修掉。
2. **`static/css/portal.css` 带了一层 HTML 外壳**。文件开头是 `"use strict";` 加 `<style>`，末尾是 `</style>`——U6.1 从 `index.html` 抽取样式时留下的残渣。浏览器把 `<style>` 当无效选择器，连带把紧随其后的 `:root{…}` 整块丢弃，于是所有 `var(--teal)`、`var(--muted)`、`var(--border)` 全部失效：登录按钮背景透明、白字看不见，卡片描边消失。删掉外壳后变量恢复，页面才回到设计稿的样子。
3. **静态资源被启发式缓存**。改完 `main.js` 后浏览器仍在跑旧文件（截图里一直报同一个旧行号）。给 `/static/` 的响应加 `Cache-Control: no-cache`（`main.py` 的 `_finish`，条件请求照常走 304），不引入 `?v=` 版本串，以免破坏 `test_frontend` 对 `src="/static/js/main.js"` 的精确断言。

另有两处文案对齐：`index.html` 的学生卡从「学号 + 出生日期登录」改为「打开校方发来的专属链接」；`staff.html` 首页删掉「我是学生」卡，改为「核验一份凭证 / 签发工作台 / 自制并签发」三张教职员动作卡。

**R3 的已知边界**：
- `/api/holder-link` 只校验签名与权限，不校验 `hashed_document` 是否真的存在于链上或 registry。给不存在的哈希签发的链接打开后是 404，不会泄漏任何东西，但会浪费一条链接。要收紧就在签发时查一次链。
- 链接里的 `sid` 是明文（base64 编码的 JSON），拿到链接的人可以解出学号。这是有意的：链接本身就是该凭证的访问权，学号随链接移交；但这也意味着「转发链接 = 转发学号」，演示时要按凭证一对一发放。
- 未设 `CAPABILITY_SECRET` 且未设 `ADMIN_TOKEN` 时，签名密钥是进程启动时随机生成的，重启即全部失效（会打 warning）。演示前请显式设一个固定值，否则中途重启会让手上的链接全部作废。
- `/me/<cap>` 与 `/api/me/<cap>` 都不在公开页的代码里，公开页只保留一个「粘贴链接」的入口。

**R2 的额外收益（未写进原计划）**：`core.js` 的 `api()` 从不主动加 `X-Admin-Token` 头，所以 U3.1 之后浏览器里的签发、注销、签发方管理在配了 token 的部署上其实一直会 401。会话 cookie 补上了这个洞——同源 `fetch` 自动带 cookie，教职员页面现在真的能用，而不只是「页面打得开」。

**R4 的取舍（说清代价）**：
- 队列在内存里（`queue.Queue`），进程重启后未发的事件丢失。对「发一封通知邮件」这个语义，宁可丢也不写盘复放——写盘复放会在重启后向陈旧地址补发。
- 去重集合 `_seen` 也是进程内的。同一凭证重启后再签发一次会再排一次队；但同一份凭证重复签发本身就会被链接受（同哈希追加新块），所以这不算新问题。
- `NOTIFY_TO` 为空时状态是 `logged`（只落库、不发信）。公开演示部署就该是这个状态：门户能记录事件，但不具备外发能力。
- 通知内容里仍带 `verify?hash=` 链接和哈希，本身不含姓名/生日——收件人由部署方决定，所以内容泄漏面也随之收敛到「知道这个哈希的人」。

**R5 的做法与代价（说清取舍）**：`rawjsondocs/` 没有被删除，它仍是 RAG、PDF 与 disclosure 的唯一来源；被移除的是它**出去的路**。持证人/学生查询改为读 `holder_index/`（一份凭证一行：学号、哈希、类型、学位），所以 zip 里没有明文姓名/生日/邮箱。提交包连 `data/` 整个不带了——包括演示私钥，接收方首次启动会自己生成新密钥并重新播种样例链。代价是：新克隆看到的链高是 3 左右，不是开发机上那条 11 高的链；截图与实物会有差异。

**仍未解决**：`authz` 在未配置任何 token 时放行（§2-D，demo-open，有意保留）；`/api/holder-link` 不校验哈希存在性（§0 已注）；`/api/notifications` 仍无鉴权（只读，内容已不含 PII）。

回滚：`baseline/index.pre_u12.html` 是拆分前的完整首页，复制回 `static/index.html` 即可复原；`app/main.py` 的两处 mount 与 `/staff*` 路由、`app/authz.py` 的会话段可一并还原。

---

---

## 1. 为什么 U11 不够

U11 做到的是：前端不渲染 tab、后端对未授权请求返回 403。但两者都在**同一个进程、同一个页面、同一份静态资源、同一套共享密钥**里。只要有一处判断写漏、静态文件被直接访问、或者演示时为了省事把 token 预填进页面，防线就整体失效。更关键的是：**学生根本不该持有的能力，仍然存在于他加载的那份 bundle 里**。

---

## 2. 已核实的暴露面（本轮新增，U11 未覆盖）

> 进度：A、B、C、E、F、G 已关闭（R0–R5）；**D（未配 token 时放行）仍保持有意开放**，因为演示与 310 条测试都建立在 demo-open 上，改成 fail-closed 需要连带改夹具与启动脚本，属于另一批工作。

| # | 暴露面 | 证据 | 严重度 |
|---|---|---|---|
| A | `/static` 整目录挂载，`index.legacy.html`（91 KB 旧原型）可被任何人直接下载 | `main.py:335` `app.mount("/static", StaticFiles(directory=str(STATIC_DIR)))`；`static/index.legacy.html` 存在 | 高：旧口径/旧文案外泄，且不受任何角色约束 |
| B | 学生查询仅凭「学号 + 8 位生日」，无令牌、无限流、无统一错误 | `main.py:1105-1130`；`rate_limit.py` 未覆盖该路由 | 高：可枚举，且返回体含完整凭证字段 |
| C | 原始凭证文档（含姓名、生日、邮箱）以明文 json 落在 `data/demo-chain/rawjsondocs/`，共 26 个文件 | `data/` 目录清点 | 高：随目录/随包分发即 PII 泄漏 |
| D | `authz.require_roles` 在未配置 token 时放行；`PUBLIC_MODE` 默认 `0` | `authz.py:75-77`；`config.py:40` | 高：默认部署即全开 |
| E | 通知收件人取请求体任意字符串 | `main.py` issue 分支 → `notifier.notify_issue(to=...)`；`index.html:275` | 中高：可被用作对外发信通道 |
| F | 单一 `index.html` 同时承载访客/学生/教职员三套界面 | `index.html:28-37`，9 个 tab 平铺 | 中：UX 根因，且有 ADMIN 标签误导 |
| G | 浏览器侧必须持有明文角色 token 才能调用写端点（无会话） | `static/js/core.js` 的 `api()` 加 header | 中：token 暴露在页面内存/脚本可读 |

**已具备、不再列为问题**（避免重复劳动）：API key 只存 SHA-256 摘要（`apikeys.py:4`）；日志字段有集中 `redact` 清单（`observability.py:52`）；审计已带 `role:` actor（`main.py:182-184`）。

---

## 3. 激进方案的六条结构性改动

### 3.1 三个入口，三套前端，物理分离（替代「一个页面九个 tab」）

- `/` → 公开验证站：只含 Verify / 公开日志 / AI 助手。产物 `static/public/index.html` + 独立 bundle。
- `/me/<capability>` → 持证人站：只含本人凭证、PDF、QR、撤销状态。产物 `static/holder/index.html`。
- `/staff` → 教职员站：签发、批量、注销、签发方、API key、审计。产物 `static/staff/index.html`。
- 三套 bundle **互不包含对方代码**；`/staff` 的 js 不出现在公开站的构建产物里。
- `/static` 改为**白名单挂载**（只允许 `css/`、`img/`、`public/`），删除 `index.legacy.html` 并从仓库移除。

判据：`curl /static/index.legacy.html` 必须 404；公开站 HTML 中 `grep -c "issue"` 命中数为 0 或仅注释。

### 3.2 身份载体从「共享密钥 header」换成「服务端会话」

- 登录：`POST /staff/login`（口令或一次性绑定码）→ 服务端建会话，返回 `Set-Cookie: sid=...; HttpOnly; SameSite=Strict; Path=/staff`，同时下发 CSRF token（双提交）。
- 会话存服务端（现有 `session_store.py` 可承载），TTL 30 分钟，空闲 10 分钟过期，退出即销毁。
- 浏览器**永不持有明文口令**；`sessionStorage` 里不再有任何凭证。
- 所有写端点改为校验会话 + CSRF，不再读 `X-Admin-Token`（该 header 仅保留给 CLI/脚本，走独立路径 `/api/issue` 且需 API key）。

判据：登录后前端内存/存储中无口令；`GET /staff` 未登录返回 302 → `/staff/login`；写端点缺 CSRF → 403。

### 3.3 用「能力链接」取代 DOB 查询（这是最激进的一条）

- 签发时为每份凭证生成 `capability`：`HMAC(key, credential_hash || exp || nonce)`，随凭证一并交付（PDF 内链接 + 学生邮件）。
- 学生访问 `/me/<capability>`：服务端校验 HMAC、绑定 hash、是否过期、是否已撤销 → 只返回该凭证的白名单字段。
- `capability` 不落明文日志；可一键吊销（撤销凭证时同步失效）。
- `/api/student/{student_id}?dob=` **从公开面移除**，仅保留在 `/staff` 内部（教职员代查）。
- 一次性模式可选：首次访问后标记 `used_at`，二次访问需重新申请（默认关闭，避免学生反复打不开）。

判据：不带 capability 访问 `/me/*` → 404；伪造/篡改 capability → 404（不区分原因）；同一 capability 在校验失效后无法读取任何字段。

### 3.4 读写分离：public 实例与 issuer 实例

- **public 实例**（可公网）：只挂验证所需索引（hash → 状态、签名公钥、撤销表），**无写端点、无私钥、无 raw 文档、无 apikeys 管理**。
- **issuer 实例**（内网/本机）：持有私钥、raw 文档、签发端点，对外只暴露只读同步接口。
- 两者共享同一份链数据（只读复制或同机不同目录），但 public 实例的目录里不存在 `rawjsondocs/`。

判据：public 实例的 `data/` 目录下 `rawjsondocs` 不存在；对 public 实例 `POST /api/issue` 返回 404（路由不存在，而非 403）。

### 3.5 通知彻底外置（前端零发送能力）

- 前端删除邮箱输入框（`index.html:275`）与一切「发送」按钮。
- 签发只产生一条**事件**（`issuance_events`），由后台 worker 消费：取凭证内邮箱 → 模板 → SMTP/干跑 → 写通知表。
- 收件人只能来自凭证 `PersonalParticulars.email`；每凭证最多 1 次成功发送 + 1 次重试；全局每分钟配额；失败进重试队列，超限告警。
- 通知内容不含完整 hash（只给前 12 位 + 短链）。

判据：篡改请求体塞 `email` → 无效（单测）；同一凭证重复签发事件 → 去重；配额触发 → 429 且记录。

### 3.6 默认拒绝 + 数据卫生（启动即校验，而不是运行时判断）

- 启动自检：无 `STAFF_TOKEN` / 无会话密钥 / `rawjsondocs` 仍在 public 目录 → **拒绝启动 staff 路由**并打印明确原因（fail-closed，且不是 403 而是不注册）。
- `PUBLIC_MODE` 语义改为「唯一支持的公网形态」；私有模式需显式 `PRIVATE_MODE=1`。
- 打包扫描：`build_package.py` 增加断言——zip 内不得出现 `rawjsondocs/`、`*.env`、`apikeys.json`、`audit-log.jsonl`。
- `data/notifications.jsonl`、`audit-log.jsonl` 保留但脱敏（邮箱打码、hash 截断）。

判据：模拟缺 token 启动 → 进程起但不含 `/staff` 路由（`/staff` 404）；打包后 zip 扫描 0 命中。

---

## 4. 与 U11 的差异（选一个执行，不要混）

| 维度 | U11（保守） | U12（激进） |
|---|---|---|
| 前端 | 一个页面，按角色显隐 tab | 三个独立站点，bundle 不交叉 |
| 身份 | 每请求带共享密钥 header | 服务端会话 + HttpOnly cookie + CSRF |
| 学生入口 | 学号 + DOB + 限速 | HMAC 能力链接，DOB 从公开面移除 |
| 部署 | 单实例 | public / issuer 读写分离 |
| 通知 | 收件人改绑凭证内邮箱 | 事件 + worker，前端零发送能力 |
| 失败姿态 | 403 | 路由不存在 + 拒绝启动 |
| 工作量 | 约 4–5 天 | 约 9–12 天 |
| 演示成本 | 低（登录一次） | 中（两个进程、链接分发） |

---

## 5. 阶段与验收（PR 粒度）

| 阶段 | 内容 | 主要文件 | 验收 |
|---|---|---|---|
| R0 | 暴露面冻结：删 `index.legacy.html`，`/static` 白名单 | `main.py:335`、`static/` | 旧页 404；白名单外 404 |
| R1 | 三入口拆分（不改后端行为，仅前端与路由） | `static/public|holder|staff/`、`main.py` 的 `GET` 路由 | 三个 URL 各自可打开；公开站 bundle 无 issue 代码 |
| R2 | 会话 + CSRF 落地，写端点改校验 | `session_store.py`、`authz.py`、`main.py` | 未登录 302；缺 CSRF 403；退出即失效 |
| R3 | 能力链接 + `/me/<cap>`，公开面撤掉 DOB 查询 | 新增 `capability.py`、`main.py` | 伪造 404、过期 404、撤销即失效 |
| R4 | 通知 worker 化，删前端邮箱框 | `notifier.py`、新增 `worker.py`、`index.html` | 请求体邮箱无效；去重；配额 |
| R5 | 读写分离与打包卫生 | `config.py`、`build_package.py`、`DEPLOY.md` | public 目录无 raw 文档；zip 扫描 0 命中 |
| R6 | 回归与交付 | `tests/`、`docs/` | 310 条全绿 + 新增矩阵用例；三入口截图；重录演示 |

每阶段独立可回退；R2 与 R3 必须同批（只做会话而 DOB 仍开放，等于没解决学生面；只做能力链接而会话未建，教职员仍持明文 token）。

---

## 6. 时间不够时的「最小激进集」（3 天）

只做 R0 + R1 + R3：

1. 删旧页、白名单挂载（半天）。
2. 三入口拆分，公开站物理上不含签发代码（1 天）。
3. 能力链接取代 DOB 公开查询（1.5 天）。

理由：这三条正好对应你提到的「学生不该 access 到发送模块」和「学生端不该暴露」；会话化与读写分离可以留到有部署需求时再做。

---

## 7. 风险与代价（必须提前认下）

| 风险 | 说明 | 处置 |
|---|---|---|
| 演示变复杂 | 两个实例 + 链接分发，现场容易翻车 | 提供 `demo_oneclick.bat` 同时起两实例并预置一条 capability 链接 |
| 会话引入 CSRF 面 | 新增攻击面 | 双提交 + `SameSite=Strict` + 写端点全部校验 |
| DOB 查询移除影响旧链接 | 旧 QR/PDF 指向 hash 验证，不受影响；仅学生自助入口受影响 | 保留 `/staff` 代查作为兜底 |
| raw 文档移出 public | 验证路径若曾依赖 raw 文档会断 | 验证只需 hash + 状态，已核实不依赖 raw |
| 工作量 9–12 天 | 课程 11 月收尾，时间紧 | 走 §6 的最小集，其余写入 backlog |

---

## 8. 明确不做

- 不做 OAuth/OIDC 接入、不做多租户、不做真实机构注册。
- 不改任何现有端点路径与公共函数签名（新能力用新模块 + 可选参数）。
- 不引入付费依赖；会话与 HMAC 均用现有 `cryptography` 与标准库。
- 不为「好看」重写设计系统；三套前端共用现有 `portal.css`。
