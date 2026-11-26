# U7 验收报告：测试深度与可观测性

批次：U7（U7.1 深度测试 / U7.2 可观测性 / U7.3 压测脚本）
日期：2026-11-13
结论：**三节全部落地并验证**。全量测试从 202 条扩到 **237 条 / 20 模块**，JSON 与 SQLite 双后端 20/20 全绿；新增请求级可观测性（关联 ID + 结构化日志 + 聚合指标 + 分层健康检查）；新增 Fuzz / 并发一致性 / 双后端对拍三类深度测试与 `--tier` 分层；新增零依赖压测脚本并取得真实基线。过程中抓到 **3 个真缺陷**（SQLite 连接泄漏、verify 路径按全链重放放大、压测脚本把 429 当错误），其中 1 个已修、1 个已量化留 U8、1 个是脚本自身缺陷已修。

---

## 1. 一句话结论

以前"出了问题只能靠复现"，现在每条请求都有 `X-Request-ID`、一行 JSON 日志、一组计数指标，`/healthz` 会说清哪一项依赖坏了而不是只给一个布尔值；同时新增 35 条测试把"畸形输入不 5xx""并发下链不丢块""两个存储后端行为一致"三件事变成可回归的断言。

---

## 2. 改动文件清单（路径 + 关键行号）

### 新增

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `app/observability.py` | 186 | 请求 ID（`REQUEST_ID_HEADER` L34）、结构化 logger（L40–46）、`SENSITIVE_KEYS`（L51）、`new_request_id()` L59、`accept_request_id()` L64、`current_request_id()` L76、`bind_request_id()` L80、`redact()` L84、`log_event()` L99、`Counters` L113（`requests`/`verdicts`/`rate_limit_denied`/`origin_denied`/`body_too_large`/`verification_total`/`duration_ms_total`/`record_request`/`record_verification`/`record_denial`/`snapshot`/`reset`）、单例 `COUNTERS` L186 |
| `tests/test_observability.py` | 221（15 条） | 请求 ID、日志形状、PII 不落日志、指标计数、标签脱敏、healthz 双契约 |
| `tests/test_fuzz.py` | 190（13 条） | 畸形 PDF / JSON / 哈希 / 批量 / 披露 / 对话，约 126 组注入负载 |
| `tests/test_concurrency.py` | 146（3 条） | 8 线程签发 + 3 线程撤销，链不丢块、可重放、判定收敛 |
| `tests/test_storage_parity.py` | 156（4 条） | json vs sqlite 五存储语义对拍 |
| `tests/tiers.py` | 52 | 模块 → `unit` / `integration` / `hardening` 注册表 |
| `scripts/load_test.py` | 161 | 零依赖压测（`http.client` + 线程池），p50/p90/p95/p99、429 单列、阈值退出码 |

### 修改

| 文件 | 行号 | 改动 |
| --- | --- | --- |
| `app/main.py` | L26–28 | `import os` / `from pathlib import Path` |
| `app/main.py` | L52 | `observability as obs` 加入 `from . import (...)` 块 |
| `app/main.py` | L109–119 | `_ID_SEGMENT_RE` + `_endpoint_label()`：16+ 位 base64url 段折叠成 `{id}`，哈希不进指标键与日志 |
| `app/main.py` | L123–208 | `_hardening_middleware` 全路径重写：顶部铸造/绑定 `rid`、`started`、`endpoint`；`_finish()` 统一做「计数 + 日志 + 写 `X-Request-ID`」，4 类出口（403 origin、413 body、401 key、429 rate_limit、正常）全部经它收口 |
| `app/main.py` | L293–326 | `/healthz` 增 `checks` 块（`chain_dir{path_exists,writable}` / `storage{backend,sqlite}` / `chain{height,signers}` / `static{dir_exists}` / `observability{...}`），`status` 由 `chain_dir_writable` 与 `static_dir` 决定 `ok`/`degraded`；顶部原有扁平常量全部保留 |
| `app/main.py` | L331–342 | 新增 `GET /api/metrics`：`COUNTERS.snapshot()` + `chain_height` + `public_mode` |
| `app/main.py` | L533–551 | `_note_verification()`：计数 + 一行 `verification` 日志（含 verdict、链高、8 字符哈希存根） |
| `app/main.py` | L565 / L623 / L733 / L828 / L839 | 埋点：`/api/verify/{hash}`、`/api/verify/document`、`/api/verify/batch`（逐行计数 + 循环后一条汇总日志）、`/api/verify/disclosure`（含 NOT FOUND 分支） |
| `app/repository.py` | L563–598 | **修缺陷**：`query()` / `ensure_schema()` 的 `with sqlite3.connect()` 只提交事务不关闭连接 → 每次查询泄漏一个句柄；改 `try/finally: conn.close()` |
| `tests/_bootstrap.py` | L33–36 | `isolated_chain_dir()` 内 `setdefault("PORTAL_LOG_LEVEL", "WARNING")`，避免 237 条测试刷屏；要断言日志的模块显式设 `INFO` |
| `scripts/run_all_tests.py` | L1–44 | MODULES 16 → 20；新增 `--tier unit/integration/hardening`；启动前校验 `tests/tiers.py` 覆盖全部模块，缺失或拼错直接 `exit 2` |

---

## 3. U7.2 可观测性：做了什么、为什么这么做

### 3.1 请求关联 ID

- 每请求铸造 16 位十六进制 `X-Request-ID`；客户端自带值**只接受** `^[A-Za-z0-9_-]{8,64}$`，不合法就**重新生成而不是清洗**——重写后的 ID 已不对应调用方原始请求，假装接受会让"按 ID 对齐两端日志"变成假线索。
- 关键点：403（跨域）/ 413（超大 body）/ 401（API Key 无效）/ 429（限流）**四个拒绝分支都在路由之前**，历史实现直接 `return JSONResponse`，这些请求既无日志也无 ID。现在四条都走 `_finish()`，因此"这条 429 是谁发的、打的是哪个端点"是可查的。

### 3.2 结构化日志与脱敏

- 单行 JSON：`{"ts","level","event","request_id", ...}`，`event` 三类：`request` / `verification` / `verification_batch`。`level` 按状态码分 info / warning。
- 脱敏按**键名**判定（`SENSITIVE_KEYS` 覆盖哈希类、邮箱、学号、DOB、令牌/口令）：哈希取前 8 字符 + `…`，邮箱留首字符 + `***@domain`，其余一律 `***`。理由：日志里的哈希若完整可就被当作检索键，等价于把凭证目录写进日志；8 字符存根足够把两条日志关联起来，不足以反查。
- 端点标签先过 `_endpoint_label()`，`/api/verify/<hash>` 落成 `/api/verify/{id}`——否则指标基数随凭证数无界增长，且哈希成了标签。

### 3.3 指标与健康检查

- `Counters` 明确标注 `shared_across_workers = False`，`/api/metrics` 把这个字段原样返回：单进程数字被读成集群数字，是比没有指标更坏的误导。
- `/healthz` 从"一个 status"变成"status + checks"：`degraded` 只由 `chain_dir_writable` 与 `static_dir` 两项决定，其余作为观察项报告（存储后端、链高、签名方数量、SQLite 文件是否存在、审计条数）。扁平老字段（`chain_name` / `height` / `content_hash_algo`）保留，`tests/test_observability.py::test_healthz_keeps_the_original_flat_fields` 守住这条契约。

---

## 4. U7.1 深度测试

### 4.1 Fuzz（`tests/test_fuzz.py`，13 条）

契约只有两条：**不出现 5xx**、**响应体不含 traceback**。输入问题该由调用方承担，500 就是有未捕获异常逃出来了。

- PDF：空 / 只有 `%PDF` / 头部正确但无对象 / `%PDF` + NUL / `%PDF` + 全字节序列 / JPEG 伪装 / `%PDF` + 尾随垃圾，分别打 `/api/extract/pdf` 与 `/api/verify/document`；再加 12 组随机二进制。
- JSON 文档形状：8 种顶层错类型、6 种缺章节/章节错类型、80 层嵌套（越过 `MAX_JSON_DEPTH`，断言必须是 422）、3 MB 字段（越过 `MAX_JSON_BYTES`）、3 种错误 Content-Type、5 种坏 JSON 文本。
- 哈希：18 种畸形（空 / 15 与 16 位边界 / 200 位 / `=` / `a+b/c` / `../` / `%00` / 中文 / 前后空格 / 换行 / `null` / `A*40+".json"` / `%2e%2e%2f`），各打 `/api/verify`、`/api/status`、`/api/pdf` 三个端点。
- 批量与披露：`{hashes: "not-a-list"}`、`[None,1,true,{},[]]`、50 个整数、`sections` 类型错等。
- 本模块关闭限流（`RATE_LIMIT_ENABLED=0`）：429 会掩盖解析行为，测的东西就变了。

**结果：0 个 5xx，0 处 traceback。** 期间发现的只有一处测试自身问题——控制字符直接塞进 URL 时 `httpx` 先抛 `InvalidURL`，改为百分号编码后再打，测的才是门户而不是客户端。

### 4.2 并发一致性（`tests/test_concurrency.py`，3 条）

不变量（不是"跑通就行"）：

1. 8 线程并发签发，**块高唯一**、全部大于起始高度、末高 ≥ 最大值——丢块会在这里暴露；
2. 3 线程同时撤销锚点凭证，全链 `verify_chain` 仍**可重放**，逐个 `load_block` 高度连续；
3. 风暴结束后判定收敛：锚点 `REVOKED`，其余 `VALID ON CHAIN`，没有 `ERROR`；
4. 撤销索引（写穿缓存）与链上重放结果一致（`revoked_records` / `revoke_meta`）。

不做的事：不比签名字节。U4.2 已经证明 RSA-PSS 随机盐、ECDSA 随机 k，按签名值比较是错的方法。

### 4.3 双后端对拍（`tests/test_storage_parity.py`，4 条）

同一脚本分别驱动 `json_repository()` 与 `sqlite_repository(path)`，比较**形状 + 生命周期结果 + 排序/截断规则**，剔除随机值（密钥、ID、时间戳）：

- API Key：创建形状、列表非空、`validate_key`、撤销后验不过、`rotate` 返回新钥且新钥可用；
- 日志 / 审计：`recent(2)` 长度与形状、`total()`、审计最近两条顺序；
- 收据 / 撤销索引：`register` 返回字符串 ID、`get` 形状、索引行形状与 `all()` 是否含目标行；
- 两个后端对未知收据都返回 `None`。

**对拍期间抓到缺陷**（见 §6.1），修后 4/4 通过且无 `ResourceWarning`。

### 4.4 分层标记（`tests/tiers.py` + `--tier`）

`unit` 4 / `integration` 14 / `hardening` 2。放在注册表而不是装饰器，是因为运行器要在**导入模块之前**决定是否起子进程——为了读一个标记去导入 20 个 app 模块，正好毁掉子进程隔离。运行器启动即校验覆盖，新测试文件不分类就 `exit 2`，不会悄悄漏掉。

---

## 5. U7.3 压测基线（真实 uvicorn，单 worker，8 并发线程，Windows 本地）

### 5.1 三组实测

| 场景 | 时长 | 请求数 | RPS | 200 | 429 | 错误率 | p50 | p90 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 匿名 IP，混合路径 | 8.04 s | 1419 | 176.6 | 829 | 590 | 0 % | 33.5 ms | 69.2 ms | 88.4 ms | 289.2 ms | 341.9 ms |
| API Key，含 `/api/verify` | 8.14 s | 505 | 62.0 | 505 | 0 | 0 % | 105.2 ms | 227.6 ms | 258.7 ms | 289.6 ms | 376.2 ms |
| API Key，SQLite 后端 | 8.15 s | 413 | 50.7 | 413 | 0 | 0 % | 138.9 ms | 276.0 ms | 306.3 ms | 372.8 ms | 403.2 ms |

**第一组数字不能当性能读**：590 个 429 是限流器的**快路径**（几十毫秒内返回、几乎不做业务工作），把它们算进 RPS 会把"限流得多快"误当"验得多快"。这正是压测脚本把 429 单列为 `throttled_429` 并**从错误率里剔除**的原因——否则一个按设计工作的限流器会被判成 41.6 % 失败率（首版就是这么误报的）。

### 5.2 慢在哪：profiler 结论

同机顺序调用 `verify_hash`（链高 2）：**24.2 ms/op**，`cProfile` 顶项：

| 函数 | 5 次调用累计 | 说明 |
| --- | --- | --- |
| `read_info` | 75 次 / 0.171 s | **单次验签内被调用 15 次**，每次重新 YAML 解析 `info.yaml` |
| `verify_block` | 20 次 / 0.143 s | 规格化 + 逐签名验证 |
| `verify_chain` | 5 次 / 0.111 s | **每次验签都对全链做一次完整性重放** |

即单次哈希验证的成本是 `O(链高 × 签名)`，而且其中一大块是重复解析同一份 YAML。链高 11 的演示链上，这就是 100 ms 量级的来源。这不是"写错了"，而是"为演示选的最保守策略"（每次验证都自证链没被改）；但**吞吐天花板随链长线性下降**是必须记录的事实，方案留 U8（见 §9）。

### 5.3 脚本自身的能力

`--max-p95-ms` / `--max-error-rate` / `--json-out` / `--api-key`，失败时退出码 1，可用于演示前排练守门；`ok == 0` 直接报"服务器是否在跑"。零新增依赖。

---

## 6. 抓到的真缺陷

### 6.1 SQLite 连接泄漏（已修，`app/repository.py` L563–598）

`with self._connect() as conn:` 在 `sqlite3` 里**只提交/回滚事务，不关闭连接**。`query()` 每调一次泄漏一个句柄，`ensure_schema()` 同样。后果：批量验证与压测下句柄持续增长，Windows 上文件被占用删不掉（对拍测试首版以 `PermissionError: [WinError 32]` 暴露），长跑最终 `too many open files` / 句柄耗尽。改为 `try/finally: conn.close()`，并保留 `execute()` 的既有写法。修复后同一测试不再出现 `ResourceWarning: unclosed database`。

### 6.2 验签路径按全链重放（已量化，留 U8）

见 §5.2。修法涉及缓存与索引，超出 U7「只加观测」的范围，不在此批偷改：**记录实测数据 + 明确方案**比顺手重构安全。

### 6.3 压测脚本把 429 当错误（脚本缺陷，已修）

首版 `error_rate = (total - 200) / total`，限流器正常工作被判 41.6 % 失败。改为 429 单列并排除，错误率只统计真实失败（5xx / 传输错误 / 预期外 4xx）。留下一条判断：**"失败率"必须定义清楚统计口径，否则指标会撒谎**。

---

## 7. 验证证据

| 项 | 结果 |
| --- | --- |
| 全量测试（JSON 后端） | **20/20 模块全绿，237 条** |
| 全量测试（SQLite 后端） | **20/20 模块全绿，237 条** |
| 逐模块分布 | api 16 / hardening 7 / features 8 / extra2 18 / employer_pack 9 / public_mode 6 / rag 32 / person 24 / restart_persistence 2 / issue_batch 5 / pdf_extract 6 / custom 8 / property_crypto 23 / chain_integrity 10 / disclosure 16 / frontend 12 / **observability 15** / **fuzz 13** / **concurrency 3** / **storage_parity 4** |
| `ruff check app` | **4 条既有基线**（`anomaly.py:71` B905、`anomaly.py:129` B007、`pdf_extractor.py:190` B007、`rag_indexer.py:318` B905）；本轮新增的 I001 已 `--select I001 --fix` 安全修复 |
| `ruff check tests` | **All checks passed**（新文件 F401/I001 安全修复，B007 手工改；未用 `--unsafe-fixes`） |
| `ruff check scripts` | 2 条既有基线（`batch_verify.py:97` B905、`build_demo_video.py:56` F841），本轮未触碰 |
| `mypy app` | **15 错误 / 6 文件 / 35 源文件**（源文件 +1 是 `observability.py`；错误数与 U6 相同，新增文件零错误） |
| 真实 uvicorn | 端口 8022（JSON）/ 8023（SQLite）实跑：`/api/demo/credentials` 200、`/api/admin/apikeys` 201、验签 200、压测三组如上 |
| 残留进程 | 已 `Stop-Process` 清理 verification-portal 下的 python |

U7 验收原文对照：
- Fuzz 无崩溃 / 无未捕获异常 → 126 组负载，0 个 5xx，0 处 traceback；
- 并发用例通过 → 8 签发 + 3 撤销，块高唯一、链可重放、判定收敛；
- 日志不含 PII / 完整哈希 → `test_log_never_carries_pii`、`test_verification_line_has_verdict_and_truncated_hash`、`test_endpoint_labels_do_not_leak_hashes` 三条断言守住；
- 指标可读取 → `GET /api/metrics` 返回请求计数、verdict 分布、拒绝分类、`shared_across_workers`。

---

## 8. TODO 全库扫描（`app/` + `tests/` + `scripts/`，U7 后）

| 位置 | 内容 | 状态 |
| --- | --- | --- |
| `app/rate_limit.py:50` | `TODO[external-redis]`：跨进程计数器 | 未解决（U2 遗留） |
| `app/session_store.py:69` | `TODO[external-redis]`：多 worker 会话共享 | 未解决（U5.3 遗留） |
| `app/session_store.py:11` | docstring 指向同一 TODO | 引用，不计 |
| `app/observability.py:16` | docstring 交叉引用 `rate_limit.py` 的 `TODO[external-redis]` | **新增引用，非新 TODO**；计数与限流器同一道缝 |
| `app/blockchain_util.py:3/13/248` | 引用 `TODO.md` 文件名 | 引用，不计 |

结论：真实待办仍是 2 条，均卡在"零依赖演示安装 vs 跨进程共享"的选择上，U7 未新增未解决 TODO。

---

## 9. 未覆盖 / 遗留（明确不做或做不到）

1. **指标不跨进程**：`Counters` 进程内自增，`shared_across_workers=False` 只是诚实标注，多 worker 下数字会各自计数；要汇总需接 Prometheus 或 Redis，属同一 `TODO[external-redis]`。
2. **`/api/metrics` 仍在限流范围内**（未加进 `_EXEMPT_PATHS`）：抓取频率受 per-IP 桶约束；是否改为 admin-only 或豁免，需与部署口径一起定。
3. **没有直方图与耗时分解**：只有 `duration_ms_total` 与端点状态计数，没有分桶直方图，p99 要靠压测脚本算。
4. **日志没有采样与轮转**：每条请求一行，生产需按大小轮转或交外部采集，当前写 stderr。
5. **Fuzz 不是持续 fuzz**：固定种子、固定语料，属于"回归式 fuzz"；真正的 libFuzzer/AFL 级探索未做。
6. **并发测试只测到线程级**：`_lock` 是进程内锁，多进程/多 worker 写入同一链目录未测（也不支持）。
7. **压测只到 8 并发**：未找拐点、未扫并发梯度（4/8/16/32），未测长稳（> 30 min）与内存增长。
8. **没有 SLO**：基线是"现在的数字"，不是"必须达到的指标"。
9. **verify 路径性能未修**：见 §5.2 / §6.2，方案留 U8（① 按 mtime 失效的 `read_info`/`trusted_signers` 缓存；② 哈希 → 块高索引替代全链线性扫描；③ 链完整性重放结果短 TTL 缓存）。
10. **`/api/metrics` 无鉴权**：公开聚合、无 PII，但拒绝计数对外可见性需确认。

---

## 10. 回滚方式

- 可观测性：删 `app/observability.py`，还原 `app/main.py` 的导入块、`_ID_SEGMENT_RE`/`_endpoint_label`、`_hardening_middleware`（恢复为无 `_finish` 的四段 `JSONResponse`）、`/healthz`（恢复 `{"status","...info"}`）、删除 `/api/metrics` 与 `_note_verification` 及 5 处调用，删 `tests/_bootstrap.py` 的 `PORTAL_LOG_LEVEL` 行。
- 深度测试：删 `tests/test_fuzz.py`、`tests/test_concurrency.py`、`tests/test_storage_parity.py`、`tests/tiers.py`，`scripts/run_all_tests.py` 的 MODULES 退回 16 项并去掉 `--tier`。
- 压测：删 `scripts/load_test.py`。
- 缺陷修复单独保留建议：`app/repository.py` 的 `conn.close()` 是必须的，不建议随其他回滚撤掉。

---

## 11. 下一批次：U8

1. **性能**：`read_info`/`trusted_signers` 按 `mtime` 缓存 + 哈希→块高索引 + 链完整性短 TTL 缓存，然后重跑 §5 三组取对照；
2. **可观测性补口**：耗时直方图、`/api/metrics` 鉴权/豁免口径、日志轮转；
3. **部署面**：`.dockerignore`（排除 `static/index.legacy.html` 与 `.venv`）、私钥口令加密（U3 移交）、`ISSUER_TOKEN`/`ALLOWED_ORIGINS` 部署口径写进 README；
4. **压测梯度**：4/8/16/32 并发 + 30 min 长稳，落 SLO 数字。
