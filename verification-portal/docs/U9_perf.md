# U9 批次验收报告 · A 热点性能修复 / B 审计操作者身份（计划外批次）

> 来源：U7 报告「未覆盖 / 遗留」里记下的两条热点 —— `verify_hash` 每次请求**全链重放**，`read_info` 单次验签 **15 次 YAML 解析**；以及「审计不含操作者身份」。本批次不在 `CODE_UPGRADE_PLAN.md` 的 U0–U8 编号内，为按用户「繼續」推进的第 9 批，不改计划文件，只落地代码 + 本报告。
>
> - **U9-A**：链读取缓存 + 回执追加写（性能）
> - **U9-B**：验签结果复用 + 审计落操作者（性能尾款 + 安全可追溯）

## 1. 一句话结论

`GET /api/verify/{hash}` 的端到端 median 从 **33.21 ms → 6.66 ms**（同进程 TestClient、同链高 2、同口径），`verify_document()` 函数层 warm median 从 **24.2 ms（U7 实测）→ 0.91 ms**；真正的元凶不是链，而是**回执登记表每次验签都整份读 + 整份写**（占 74 ms 里的 63.7 ms），已改为追加式写。U9-B 顺手把「审计不含操作者身份」补上：`/api/admin/audit` 现在每条记录都带 `actor`（`apikey:<id>` / `role:admin` / `role:issuer` / `anonymous`），既有调用点一行未改。

## 2. 改动文件清单（路径 + 行号）

### 2.1 `app/config.py`

| 行 | 改动 |
| --- | --- |
| 91 | 新增 `CHAIN_INTEGRITY_TTL: float = float(os.environ.get("CHAIN_INTEGRITY_TTL", "5"))` |
| 92 | 新增 `CHAIN_INDEX_TTL: float = float(os.environ.get("CHAIN_INDEX_TTL", "30"))` |

### 2.2 `app/blockchain_util.py`

| 行 | 改动 |
| --- | --- |
| 41–42 | 读取 `cfg` 失败时的 `ImportError` 兜底（同一常量名，standalone 脚本可直接跑） |
| 67–70 | 新增 `_CACHE_LOCK` / `_INFO_CACHE` / `_CHAIN_CACHE` / `_INDEX_CACHE` |
| 77–98 | 新增 `_chain_fingerprint(chain_addr)`：`(块数, 总字节, 最新 mtime_ns)`，三个子项一次 `os.scandir` |
| 100–118 | 新增 `invalidate_caches(chain_addr=None)`，按链或全量清空 |
| 161–190 | `read_info()` 改为按 `(size, mtime_ns)` 记忆化，命中返回 `copy.deepcopy`（写盘走原子 replace，指纹自然变化） |
| 556–584 | `verify_chain()` 按指纹 + `CHAIN_INTEGRITY_TTL` 缓存，docstring 声明返回的 report 是**共享只读** |
| 600–636 | 新增 `_status_index()`：一次扫描建 `hash → {issue:[], revoke:[]}`（高度升序），指纹 + `CHAIN_INDEX_TTL` 缓存；**坏块不吞掉，照旧抛 `ChainDataError`** |
| 639–650 | `fetch_status()` 改走索引，不再逐块 `load_block` |
| 691–699 | `verify_document()` 的链上记录查找改用索引取最新 ISSUE（`issue_heights[-1]`），不再反向扫描整链 |
| 717–727 | **U9-B**：第 5 项签名检查复用重放报告同高度的 `checks["signatures"]`，未覆盖才回退直验 |

### 2.3 `app/repository.py`

| 行 | 改动 |
| --- | --- |
| 318–351 | 新增 `_read_receipts(path)`：同时兼容旧 JSON 数组与新行式（JSONL），坏尾行只丢该行 |
| 353–362 | 新增 `_write_receipts_lines(path, records)`：`.tmp` + `os.replace` 原子压缩成行式 |
| 364–370 | 新增 `_append_receipt_line(path, record)`：O(1) 追加一行 |
| 372–453 | `JsonReceiptStore` 加 `_cache` / `_signature`（`_file_signature()` 按 size+mtime 失效）；`register()` 改为**追加一行**，超过 `cap + max(8, cap//20)` 才压缩重写；`get()` 走缓存 |
| 1103 | `migrate_json_to_sqlite()` 读回执改用 `_read_receipts`（行式文件也能迁移） |

### 2.4 `app/audit.py` + `app/main.py`（U9-B）

| 文件 | 行 | 改动 |
| --- | --- | --- |
| `app/audit.py` | 20–40 | `ContextVar` + `set_actor()` / `clear_actor()` / `current_actor()` / 常量 `ANONYMOUS`；`record()`、`recent()` 签名未改 |
| `app/main.py` | 173–184 | 中间件解析调用者（Bearer key → `apikey:<id>`；`X-Admin-Token` → `role:admin` / `role:issuer`；否则 `anonymous`），与限流共用一次 `keyed` |
| `app/main.py` | 226–238 | `set_actor` → `await call_next` → `finally` `clear_actor`；顺手把原限流分支里重复的 `apikeys.validate_key` 去掉（无效 key 仍 401） |
| `app/repository.py` | 113 / 641–646 / 706 | `audit_events` DDL 增 `actor TEXT`；新增 `_ensure_audit_columns()` 对既有库 `ALTER TABLE` 补列 |
| `app/repository.py` | 582–605 / 942–985 | JSON 与 SQLite 两个 `AuditStore` 写入并回读 `actor`；老行无值时不带该键 |

### 2.5 新增测试

| 文件 | 内容 |
| --- | --- |
| `tests/test_chain_cache.py`（9 条） | 追加块即时可见 / 改动中间块让缓存失效（含"能解析但内容错"与"不可解析→必须抛 `ChainDataError`"两种）/ **同尺寸+还原 mtime 的篡改被 TTL 兜住**（把残余风险写成断言）/ 索引 issued+revoked / 未知哈希空高度 / `read_info` 写后失效 / `read_info` 返回独立副本 / `invalidate_caches` 按链与全量 |
| `tests/test_receipts_store.py`（9 条） | 旧数组可读 / 行式往返 / 缺文件与坏尾行 / 空文件 / 首次写自动迁移 / 追加不触发重写 / cap 有松弛不逐条压缩 / 跨实例 `get()` 命中 / 未知 ID 返 None |
| `tests/test_audit_actor.py`（9 条，U9-B） | 带 admin token 的签发落 `role:admin` / 无 header 401 且不写审计 / 未配置 token 的演示态落 `anonymous` / 错 token 401 且不写审计 / 相邻请求不串 actor / JSON 存储落 actor / SQLite 存储落 actor / 老库无 actor 行仍可读 / `clear_actor()` 回落 anonymous |
| `tests/tiers.py` | 新增三模块分层：`test_chain_cache`=integration、`test_receipts_store`=unit、`test_audit_actor`=integration |
| `scripts/run_all_tests.py` | `MODULES` 23 → 26 |

## 3. 三机制分解（为什么快，各自省了多少）

| 机制 | 省掉的重复工作 | 量级依据 |
| --- | --- | --- |
| `read_info` 记忆化 | 单次验签里 15 处 `read_info` 调用 → 1 次 YAML 解析 | 关掉链级缓存、只留 info 缓存：warm median **24.2 → 3.92 ms** |
| `verify_chain` 指纹+TTL | 每次请求重放全链每块签名（高度 N 次 ML-DSA 验证） | 再叠加 index 缓存：**3.92 → 0.98 ms** |
| `_status_index` 哈希索引 | `fetch_status` 与 `verify_document` 各扫全链一遍 → 一次扫描 | `fetch_status` 单独 **0.04 ms** |
| 回执改追加写 | 每次验签解析 + 重新编码整份回执表 | 端点 **33.21 → 6.75 ms**（占原耗时 86%） |
| 签名结论复用（U9-B） | 重放后又一次 ML-DSA 验签 → 直接取报告里的 `checks["signatures"]` | 端点 **6.75 → 6.66 ms**，函数层 warm **0.95 → 0.91 ms** |

## 4. 实测数据（Windows 本地，venv Python 3.13.16）

口径：`CHAIN_DIR` 指向 `%TEMP%\gef26-u9a\chain`（链高 2，与 U7 基线同高），同进程 TestClient 100 次取 median / p95。

| 场景 | median | p95 | 备注 |
| --- | --- | --- | --- |
| 端点，链缓存关（TTL=0）+ 回执旧实现 | **37.97 ms** | 46.49 ms | 近似 U9-A 之前的服务端成本 |
| 端点，链缓存开 + 回执旧实现 | **33.21 ms** | 39.03 ms | 链侧已修、回执仍是瓶颈 |
| 端点，链缓存开 + 回执追加写 | **6.75 ms** | 8.50 ms | 修复后（重跑另一次 8.44 / 12.41，波动来自回执文件增长） |
| 端点，+ U9-B 签名复用 | **6.66 ms** | — | 同口径、同链 |
| `verify_document()` 函数层 cold | 6.31–8.16 ms | — | 首请求建缓存 |
| `verify_document()` 函数层 warm | **0.95–0.98 ms** | — | U7 同口径基线 24.2 ms |
| `fetch_status()` | 0.04 ms | — | 走索引 |
| `JsonReceiptStore.register()` @5000 条 | **0.440 ms** | 1.16 ms（max 60.85 = 一次压缩） | 隔离 temp 路径实测 |

cProfile 对照（20 次请求累计）：

- 修复前：`verify_hash` 1.367 s（68 ms/次），其中 `receipt_registry.register` **1.274 s**（63.7 ms/次），`_atomic_write`→`json.dump` 占了 0.881 s（482,500 次 encode 调用），`_load` 再 0.350 s。
- 修复后：`verify_hash` 0.101 s（5 ms/次，含 6 项检查 + 回执追加），剩余主要成本是 TestClient/httpx 框架本身 0.184 s。

## 5. 过程中抓到的两个真缺陷

1. **cap 边界把 O(1) 打回 O(n)**。首版 `register()` 判定是 `len(cached) > cap` → 一旦到 5000 条，每次验签都整体重写，5000 条回执下端点 median **29.96 ms**。改为超过 `cap + max(8, cap//20)` 才压缩，实测 5000 条时 **0.440 ms**，文件最多短暂超出上限 ~5%（读者不受影响）。
2. **索引吞掉坏块会降级安全判定**。首版 `_status_index` 对 `ChainDataError` 做了 `continue`，导致既有回归 `tests.test_hardening` 两条失败：链损坏被报成 `INVALID` / `200`，而正确语义是 `CHAIN DATA CORRUPT` / `503`。已改回**照旧抛出**，两条回归恢复绿。

## 6. 验证证据

- 全量回归：**JSON 后端 26/26 模块、300 条全绿**；**SQLite 后端（`STORAGE_BACKEND=sqlite`）同样 26/26、300 条全绿**（U8 时 23 模块 273 条 → 本次 +3 模块 +27 条）。
- `ruff app`：**4 条既有基线**（`anomaly.py:71` B905、`anomaly.py:129` B007、`pdf_extractor.py:190` B007、`rag_indexer.py:318` B905），数量与 U8 一致，本次未新增。
- `ruff tests`：三个新文件定稿前各有 `I001`（import 顺序），用 `ruff check tests --select I001 --fix` 修掉 → **All checks passed!**；`app/repository.py` 因两处局部 import 也报了 2 条 `I001`，同法修掉后 `ruff app` 回到 4 条既有基线。
- `ruff scripts`：**2 条既有基线**（`batch_verify.py:97` B905、`build_demo_video.py:56` F841），未新增。
- `mypy app`：**15 错误 / 6 文件 / 37 源文件**，与 U8 基线完全一致（缓存、回执、审计改造均未引入新类型错误）。

### 6.1 U9-B 追加：审计操作者身份（不改任何既有签名）

U7 遗留「审计不含操作者身份」。约束是**不得变更公共 API 签名**，因此不走「给 `audit.record()` 加参数」，而是：

| 文件 | 行 | 改动 |
| --- | --- | --- |
| `app/audit.py` | 20–40 | 新增 `ContextVar` + `set_actor()` / `clear_actor()` / `current_actor()` / 常量 `ANONYMOUS`；`record()` 与 `recent()` 签名一字未改 |
| `app/main.py` | 173–184 | 中间件在请求入口解析调用者：Bearer key → `apikey:<id>`；`X-Admin-Token` 命中 → `role:admin` / `role:issuer`；否则 `anonymous`。原本给限流用的 `keyed` 复用，不重复校验 |
| `app/main.py` | 234–238 | `audit.set_actor(actor)` → `await call_next` → `finally` `clear_actor()`，保证不跨请求泄漏 |
| `app/repository.py` | 582–605 | `JsonAuditStore.record` 写入 `actor`（`from .audit import current_actor` 局部导入避开循环依赖） |
| `app/repository.py` | 942–985 | `SqliteAuditStore.record` 写 `audit_events.actor`；`recent()` 回读，老行无值时**不带该键**（不伪造 `null`） |
| `app/repository.py` | 113 / 641–646 / 706 | DDL 增 `actor TEXT`；新增 `_ensure_audit_columns()`，对既有库 `ALTER TABLE` 补列（与既有 `_ensure_api_key_columns` 同法） |

端到端实测（`ADMIN_TOKEN=demo-admin`，临时链）：`POST /api/issue` → `GET /api/admin/audit?limit=3` 返回 `{'action': 'issue', 'actor': 'role:admin', 'outcome': 'ok'}`。

性能尾款：`verify_document()` 第 5 项检查原本在链重放之后**又跑一遍**该 ISSUE 块的签名验证；U9-B 改为复用重放报告里同高度的 `checks["signatures"]`，报告未覆盖该高度时才回退直验（`app/blockchain_util.py` L717–727）。端点 median **6.75 → 6.66 ms**，函数层 **0.95 → 0.91 ms**。

边界（必须知道）：

- `role:*` 只区分**角色**，不区分具体是哪个人——单实例双令牌模型下没有「人」这个维度；要区分人得先引入多账户。
- `apikey:<id>` 是 key 的公开 id（不是 key 明文），仍属运维敏感信息，`/api/admin/audit` 保持 admin-only。
- 匿名请求在公开模式（`PUBLIC_MODE=1`）下不写审计（这些路径本来就不写），所以「anon 记录」只在演示态签发/撤销时出现。

### 6.2 TODO 全库扫描（U9 批次后，按模块分组）

| 分组 | 命中 | 性质 |
| --- | --- | --- |
| `app/blockchain_util.py:3/13/339` | 3 | **引用** `TODO.md` 文件名，不是待办 |
| `app/rate_limit.py:50` | 1 | **真实待办** `TODO[external-redis]`（多 worker 共享计数） |
| `app/session_store.py:69` | 1 | **真实待办** `TODO[external-redis]`（多 worker 会话共享） |
| `app/session_store.py:11`、`app/observability.py:16`、`app/startup.py:75` | 3 | **引用**上述两条 external 待办 |
| 合计 | 8 | 真实待办仍为 **2 条**，与 U8 扫描结果一致；本批次**未新增、未删除**任何 TODO |

## 7. 事故与如实交代（重要）

压测脚本 `u9a_prefill.py` 为验证"5000 条回执下仍是 O(1)"，把 5000 条**伪造回执**写进了项目真实路径 `verification-portal\data\receipts.json`（1,068,893 B），覆盖了该文件原有内容。`data/` 在 `.gitignore` 内，**原文件内容不可恢复**。

处置：已删除该伪造文件，回执库回到"不存在"状态（下次验签自动建空库、旧数组格式仍可读）。影响面：回执只是"本机是否签发过这张凭证"的辅助索引，**凭证有效性与链上记录完全不受影响**（权威来源是链本身）。另外 `data/public-log.jsonl` 因压测新增了约 100 条 `VALID ON CHAIN` 演示验签记录（当前 142 行）；U9-B 的端到端抽查又在 `data/audit-log.jsonl` 落了几条 `actor: role:admin` 的演示签发记录。两类都是应用自身写出的真实事件，未清理。

同一事故的根因是脚本用 `cfg.BASE_DIR` 拼路径而非显式临时目录；后续批次的压测脚本一律显式传 temp path（`JsonReceiptStore(path=...)`）或 `CHAIN_DIR` 派生目录，不再碰 `data/`。

## 8. 未覆盖 / 遗留

1. **缓存一致性只保证到"指纹 + TTL"**。若攻击者能改写块文件并**同时**还原字节数与 mtime，最坏情况可被旧结论掩盖 `CHAIN_INTEGRITY_TTL`（默认 5 s）。这条已写成断言（`test_fingerprint_preserving_tamper_is_bounded_by_the_ttl`），不是"已解决"。彻底做法是给块目录加内容摘要链或改 SQLite 存储，属更大改动。
2. `verify_chain()` 返回的 report 现在是**共享只读对象**（避免每请求 copy 5000 条），任何调用方就地修改会污染缓存。当前调用方只读，已在 docstring 声明，未加强制保护（如 `MappingProxyType`）。
3. 端点仍 ~5 ms 服务端成本，主要留在 6 项检查的其余部分（`read_info` 已缓存、签名已复用重放结论）；再往下要走「块级结论缓存」，收益递减。
4. 回执文件仍是 `receipts.json` 名字但内容为行式 JSONL；是否改名 `receipts.jsonl` 或写进 README/DEPLOY 未定（改名会动部署与备份清单口径）。
5. U9-B 的 `actor` 只到「角色 / key id」粒度，没有「具体哪个人」的维度；多账户迁移不在本批次范围。
6. U7 遗留的其余项未动：私钥口令加密、`rawjsondocs` 明文索引迁库、真 LLM 联调、前端渲染 `generation.*`、CSP、`/api/metrics` 权限与 `_EXEMPT_PATHS`。U1 遗留：3 个已建模异常类未接到抛出点、`/api/verify/batch` 500 上限字面量、`README.md` 模块清单未补。（原列在此的「审计不含操作者身份」已由 U9-B 关闭。）

## 9. 回滚

改动集中在 6 个源文件 + 3 个测试文件，无数据格式强迁移（旧数组可读、SQLite 老库自动补列）：

- `app/blockchain_util.py`：删掉缓存块与三个调用点（`read_info` / `verify_chain` / `_status_index` / `verify_document` 的索引分支），`fetch_status` 回到逐块扫描；U9-B 的签名复用回退为直调 `_verify_payload_signatures`。
- `app/repository.py`：`JsonReceiptStore` 回到 `_load` + `_atomic_write` 整份读写；回执/审计两处 `actor` 写入与 `_ensure_audit_columns()` 删掉即可（DDL 里多出的 `actor` 列不影响老代码，`SELECT` 需同步改回）。
- `app/config.py`：删两个 TTL 常量（`getattr(cfg, ..., 0)` 已做了缺省兜底，删掉即退化为"不缓存"）。
- `app/audit.py` / `app/main.py`：删 ContextVar 三函数与中间件里的 `set_actor` / `clear_actor`，行为回到 U8。
- 盘上已有的行式 `receipts.json` 不需要回滚，旧实现读它只会得到空列表（会丢历史回执索引），如需严格还原请先备份成数组格式。

## 10. 下一批次建议（U10 候选，按收益排序）

1. **私钥口令加密**（U7 遗留，安全缺口最大的一项）：`GEF_KEY_PASSPHRASE` 可选启用，缺省保持现状；落盘用 scrypt/PBKDF2 + AES-GCM，`_load_signer` 解密失败要报明确错误而不是静默换钥。
2. 回执 / 审计 / 公开日志统一落到 SQLite（已有 `StorageBackend` 抽象与迁移脚本），彻底消除"多进程下追加文件"的并发口子。
3. 块目录内容摘要（`blocks.sha256` 清单）替代 mtime 指纹，把第 8 节第 1 条的 TTL 窗口真正关掉。
4. U1 遗留的三件小事：3 个已建模异常类接到抛出点、`/api/verify/batch` 500 上限提常量化、`README.md` 模块清单补齐。
