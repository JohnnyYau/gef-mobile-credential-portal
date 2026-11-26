# U8 验收报告：部署可靠性与依赖治理

批次：U8（U8.1 持久化与备份 / U8.2 配置与启停 / U8.3 依赖治理）
日期：2026-11-13 · 代码根：`verification-portal/` · 运行环境：Windows 本地，venv Python 3.13.16
状态：**三批全部落地，273 条测试 / 23 模块在 JSON 与 SQLite 两种后端下全绿**

---

## 0. 一句话结论

U8 把"能跑起来"升级为"能证明自己跑对了"：备份包自带逐文件 SHA-256 清单，导入先解到暂存目录校验完才改名就位，启动恢复对 tar 成员做链接/设备/绝对路径三层拒绝；启动期配置校验把 5 类致命错误和 7 类降级项一次性说清，关闭时释放仓储句柄；依赖侧给出 49 个分发、44 permissive / 5 annotated / **0 GPL** 的许可证清单，镜像按 CPU-only 分层且可选 ML 依赖缺失有测试兜底。

---

## 1. 改动文件清单（路径 + 行号）

### U8.1 持久化与备份

| 文件 | 行数 | 关键行 |
| --- | --- | --- |
| `app/backup.py`（新增） | 206 | L39 `_is_unsafe_path()`、L55 `sha256_of()`、L63 `safe_members()`、L82 `extract_safely()`、L93 `build_manifest()`、L114 `manifest_bytes()`、L119 `read_manifest()`、L137 `audit_restored()`、L170 `verify_archive()` |
| `scripts/backup_chain.py`（重写） | 204 | L41 `_chain_facts()`、L51 `_members_for_export()`、L70 `export_chain()`、L111 `import_chain()`、L164 `verify_chain_archive()`、L178 `main()`（export/verify/import 三子命令） |
| `scripts/restore_drill.py`（新增） | 126 | L38 `_step()`、L44 `_first_issue_hash()`、L61 `run()`（6 步演练，`--keep` 保留现场） |
| `app/chain_core.py`（改） | — | L24 `from . import backup, …`；L187 `restore_snapshot_if_needed()` 改用 `extract_safely` + `read_manifest` + `audit_restored` |
| `tests/test_backup.py`（新增） | 326 | 15 条：往返、`--exclude-keys`、翻字节被拒、缺成员被拒、`..`/绝对/symlink/hardlink/device 五种成员、非空目标、无清单旧包、启动恢复正反例 + symlink 中止 + 清单篡改中止 |
| `docs/DEPLOY.md`（改） | — | 新增 1.1「卷与必须落盘的内容」表、1.2「快照格式（U8.1）」 |

### U8.2 配置与启停

| 文件 | 行数 | 关键行 |
| --- | --- | --- |
| `app/startup.py`（新增） | 118 | L32 `_writable_dir()`、L40 `validate_config()`（fatal / warnings 分支）、L114 `describe()` |
| `app/main.py`（改） | — | L99 `CONFIG_REPORT`、L103 `_lifespan()`（校验→恢复→播种→关闭收口，L113/L114 写入报告）、L327 `healthz()`、L357–359 `checks.config` |
| `app/repository.py`（改） | — | L600 `SqliteBackend.close()`（显式空实现 + 原因）、L894 `Repository.close()`、L919 `close_all()` |
| `tests/test_startup.py`（新增） | 173 | 16 条：11 条配置分支、fatal 拒绝启动、缓存关闭/重建、healthz 计数 |

### U8.3 依赖治理

| 文件 | 行数 | 关键行 |
| --- | --- | --- |
| `scripts/license_audit.py`（新增） | 179 | L42 `_licence_text()`、L60 `classify()`、L76 `installed_packages()`、L87 `direct_dependencies()`、L100 `render_markdown()`、L135 `main()`（`--check` 可做 CI 闸门） |
| `docs/SBOM.md` / `docs/SBOM.json`（新增） | 56 / — | 生成产物，逐分发一行 |
| `Dockerfile`（重写） | 46 | 三层：L17 `COPY requirements-lock.txt` → L21 安装 → L27 `ARG INSTALL_ML` 可选 CPU torch → L35 `COPY app/static`；L40 非 root `portal`；L43 `HEALTHCHECK` |
| `.dockerignore`（新增） | 18 | 排除 `.venv/`、`data/`、`tests/`、`scripts/`、`static/index.legacy.html` |
| `tests/test_optional_deps.py`（新增） | 114 | 5 条：无 sentence-transformers / 无 faiss / 无 sklearn / 无 qrcode |
| `requirements-lock.txt`（改） | — | 头部注释改为指向 `docs/SBOM.md` |
| `tests/tiers.py`、`scripts/run_all_tests.py`（改） | — | 注册 3 个新模块，MODULES 20 → 23 |

---

## 2. U8.1：备份 → 校验 → 恢复

### 2.1 清单格式

`MANIFEST.json`（`app/backup.py:93`）随包写入，字段：

```json
{"format": "gef26-chain-snapshot-v1", "created_at": "...Z",
 "chain_name": "Gef26-credential-chain", "height": 2,
 "includes_private_keys": true,
 "files": [{"path": "blocks/block-000000000.json", "size": 1531, "sha256": "…"}]}
```

`height` 与 `includes_private_keys` 是给运维看的：拿到一个包，先知道它是哪条链、多高、有没有私钥，再决定能不能签新凭证。`--exclude-keys` 会同步写 `true/false`，不会出现"包里没私钥但清单声称有"的静默误导。

### 2.2 成员安全：五种拒绝 + 一条路径判定

`safe_members()`（`app/backup.py:63`）在解包前拒绝：绝对路径、`..`、symlink、hardlink、字符/块设备与 FIFO。抽查 U8.1 修掉的三个真实缺陷：

1. **`Path.is_absolute()` 是平台相关的**。Windows 上 `/tmp/escaped.txt` 不是绝对路径（无盘符），一份 Linux 造的绝对路径包会在 Windows 端被判"安全"。改为按字符串形态判定（`/`、`\`、`\\`、盘符正则），见 `_is_unsafe_path()` L39。
2. **清单里有、归档里没有的成员会让校验直接崩**。`tf.getmember()` 抛 `KeyError`，调用方拿到的是 traceback 而不是"缺文件"。改为捕获并记为 `missing member: …`（L170 起）。
3. **无清单旧包自相矛盾**。旧逻辑把"没有 MANIFEST"写进 problems 又 `return not problems`，于是旧包恒判失败——和"旧包应可导入但只给提示"直接冲突。改为把无清单当**提示**（`ok=True`，附 `no MANIFEST.json (pre-U8.1 export): contents not verified`），只有真的缺 `info.yaml` 才失败。

解包统一走 `extract_safely()`（L82）：Python ≥3.12 用 `filter="data"`（PEP 706 会再拒一层链接与设备），回退分支依赖上面的手检，运行时差异不影响安全性。

### 2.3 导入：先暂存，再改名

`import_chain()`（`scripts/backup_chain.py:111`）的顺序是：`verify_archive` → 解到 `<dir>.restoring` → 按清单 `audit_restored` → 清空暂存 → `rename` 就位。任一步失败都 `finally` 清理暂存，**目标目录从未被创建或改写**。测试 `test_flipped_byte_fails_verification_and_import` 断言"被拒的导入不产生目标目录"，`test_non_empty_target_is_refused` 断言"拒绝时不动已有内容"（写了个 `keep-me.txt` 验证仍然在）。

`audit_restored()`（L137）额外报 **多余文件**：链目录里出现清单外的文件，正是一次恢复该暴露的事，而不是忽略。

### 2.4 启动恢复

`restore_snapshot_if_needed()`（`app/chain_core.py:187`）原来只挡 `..` 和绝对路径，symlink 可穿过它写到链目录外。现在：成员校验 → 解包 → 清单校验（有清单时逐文件 SHA-256）→ 缺 `info.yaml` 或清单不符一律 `RuntimeError` 中止启动。**宁可空链重新播种，也不带着半条无法自证的链对外判 VALID。**

### 2.5 演练（实测）

`scripts/restore_drill.py` 在独立链目录（`CHAIN_DIR=%TEMP%\gef26-u81b\chain`，链高 2）跑出：

```
[PASS] export — snapshot.tar.gz (12290 B)   manifest: chain=Gef26-credential-chain height=2 keys=yes files=8
[PASS] verify archive — height=2 files=8
[PASS] import — restored 12 entries          (height 2, checksums verified)
[PASS] chain replay — clean
[PASS] credential comparison — hash GFiY4d67… issued=True revoked=False issue_heights=[1]
[PASS] height matches — 2 → 2

6/6 drill steps passed
```

第 5 步是这条演练真正的价值：不只是"链能重放"，而是"同一个凭证哈希在恢复后的链上判定一致"。首版这里写错过——`fetch_status()` 返回的键是 `issue_heights`（列表）而不是 `issue_height`，当时两侧都取到 `None` 于是"相等"，属于假通过；已改成整字典比较。

### 2.6 部署口径（写进 DEPLOY）

新增 1.1 表，把"什么必须落盘"列清楚：`blocks/`、`info.yaml`、`keys/`、`rawjsondocs/`、以及 `SQLITE_PATH`。要点是**一个卷同时挂 `CHAIN_DIR` 与 `SQLITE_PATH`**——只挂 `CHAIN_DIR` 会得到一个"凭证还在、回执/审计/API Key 全丢"的半持久化实例。免费层临时存储的后果也写明了：签发过的凭证在重启后不存在，除非有快照。

---

## 3. U8.2：启动校验与优雅关闭

### 3.1 校验清单

`validate_config()`（`app/startup.py:40`）分两级，判据是"这个进程还能不能给出正确答复"：

**fatal（拒绝启动）**
- `STORAGE_BACKEND` 不是 `json`/`sqlite`（历史行为是静默回落 JSON，等于用另一种存储假装成功）
- `CHAIN_DIR` 父目录不可写
- `STORAGE_BACKEND=sqlite` 时 `SQLITE_PATH` 父目录不可写

**warning（启动但记录降级）**
- `STATIC_DIR` 缺失（UI 404，API 仍可用）
- `SESSION_BACKEND` 未知 / `redis`（占位实现，会话留在进程内）
- `PUBLIC_MODE=1` 同时设了 `ADMIN_TOKEN`（admin 端点全 403，令牌无效）
- `EMAIL_ENABLED=1` 缺 `SMTP_HOST`（通知 dry-run，不出机器）
- 设了 `CHAIN_SNAPSHOT_URL` 但 `CHAIN_DIR` 非空（快照被忽略）
- 两个 `RATE_LIMIT_*_MAX` 都 ≤ 0（限流放行一切）
- `ALLOWED_ORIGINS` 为空而 `PUBLIC_BASE_URL` 是公网 https（跨源 POST 会被 403）
- `PORTAL_LOG_LEVEL` 不是合法级别

取舍写在模块 docstring 里：演示实例不该因为缺一个邮件服务器就起不来，但**不能**起在一个自己没实现的存储后端上——那种情况下每一条 "VALID" 都在为一个从未落盘的数据背书。

### 3.2 接线

`_lifespan`（`app/main.py:103`）顺序改为：校验 → 有致命项则抛 `RuntimeError`（`test_fatal_config_refuses_to_start` 覆盖）→ 记录 warnings（走 `obs.log_event`，带 request 无关的 `event=config`）→ 可选快照恢复 → `ensure_chain`。启动失败路径也会 `repository.close_all()`，不把缓存的 bundle 留在半初始化状态。

`/healthz` 增加 `checks.config = {fatal, warnings}`（L357–359）：部署后能复核，而不是只能翻启动日志。

### 3.3 关闭

`Repository.close()`（`app/repository.py:894`）按 `_db` 去重收集底层引擎并调用其 `close()`；`close_all()`（L919）清缓存并返回 bundle 数，`_lifespan` 的 `finally` 调用它并记 `event=shutdown bundles_closed=N`。

`SqliteBackend.close()`（L600）是**显式空实现**，注释说明原因：本实现的连接是每次调用短连接，`query()`（L589）已在 `finally` 里 `conn.close()`，所以现在没有常驻句柄。留这个口令是为了让"关闭释放仓储"在换连接池后端（Redis/Postgres）之前就是一个可调用的契约——一个永不被调用的 no-op 会在那天变成真泄漏。

**后台任务**：全库 grep `threading.Thread|Timer(|ThreadPoolExecutor|daemon=|.start()` 在 `app/` 下 **0 命中**，本服务不派生线程/定时器，退出期不需要 join；唯一常驻状态是仓储缓存与链锁，前者已释放，后者随进程结束。

---

## 4. U8.3：依赖治理

### 4.1 许可证清单（实测）

`scripts/license_audit.py` 扫当前 venv 的 `importlib.metadata`，排除 tooling（pip/setuptools/wheel）：

```
scanned 49 distributions -> docs/SBOM.md
  OK 44 | NOTE 5 | BLOCK/UNKNOWN 0
  NOTE  certifi 2026.10.19: MPL-2.0
  NOTE  cryptography 50.0.2: Apache-2.0 OR BSD-3-Clause
  NOTE  hypothesis 6.170.15: MPL-2.0
  NOTE  packaging 26.3: Apache-2.0 OR BSD-2-Clause
  NOTE  pathspec 1.1.1: MPL-2.0
```

判定规则与用户口径一致：MIT/BSD/Apache/ISC/PSF → OK；MPL-2.0 与 LGPL → **NOTE（可用但必须标注）**；GPL/AGPL/专有 → BLOCK；无元数据 → UNKNOWN 视同 BLOCK。**当前 0 条 BLOCK、0 条 UNKNOWN**。

5 条 NOTE 的实际含义（写进 `docs/SBOM.md` 正文，避免"NOTE 等于有问题"的误读）：

- `certifi` / `pathspec`：MPL-2.0，仅作为未修改的库使用（certifi 供 TLS 根证书、pathspec 是 ruff 的依赖）。
- `cryptography` / `packaging`：Apache-2.0 **或** BSD 双许可，我们取宽松分支。
- `hypothesis`：MPL-2.0，仅测试期依赖，不进镜像。

`--check` 在存在 BLOCK/UNKNOWN 时返回 1，可直接进 CI。清单是**生成物**：依赖一变就重跑，不靠人工维护表格。

### 4.2 镜像分层（CPU-only）

`Dockerfile` 重写为三层，冷重建的代价只落在真正变化的那层：

1. `COPY requirements-lock.txt` → 安装锁定集（可复现安装用的是 lock，不是宽松 ranges）
2. `ARG INSTALL_ML=0`：**默认不装 torch**。`INSTALL_ML=1` 时从 `download.pytorch.org/whl/cpu` 装 CPU 轮子，再装 `sentence-transformers` / `faiss-cpu` / `scikit-learn`
3. `COPY app ./app` + `COPY static ./static`（代码改动只失效这一层）

附带：`PIP_NO_CACHE_DIR`/`PYTHONUNBUFFERED`、非 root 用户 `portal`（uid 10001）、`HEALTHCHECK` 打 `/healthz`。

**这里有一个刻意的取舍**：旧 Dockerfile 无条件装 torch，但 `requirements.txt` 的 ML 依赖在锁文件里并不存在——即"镜像多背几百 MB，却仍走哈希 embedder"的中间态。改成默认 `INSTALL_ML=0` 后，瘦镜像 = 哈希 embedder + numpy 检索（文档化的降级路径，有测试覆盖）；要真语义检索就显式 `--build-arg INSTALL_ML=1`。

`.dockerignore` 补上（原先不存在）：`.venv/`（100+ MB）、`data/`（演示链数据）、`tests/`、`scripts/`、`static/index.legacy.html`（U6 回滚基线，不该进镜像）。

### 4.3 可选依赖降级（有测试）

`tests/test_optional_deps.py` 用 `import_blocked()` 把 `__import__` 拦在根模块上，复现"部署镜像里没装"的情形：

| 缺失包 | 断言 |
| --- | --- |
| `sentence-transformers` | `Embedder.backend == "hash-ngrams-v1"`，dim 1024，行 L2 范数 ≈ 1（分数与后端无关可比） |
| `faiss` | `_build_vector_index()` 返回 `None`；`_vector_search()` 用 numpy 余弦排序，精确轴向量排第一 |
| `scikit-learn` | `_isolation_flags()` 返回 `None`；`detect()` 报告 `method == "rule_based"`（不冒充模型输出） |
| `qrcode` | `GET /api/qr/{hash}` → 503 且 detail 含 `qrcode` |

这类属性最容易被"顺手提到顶层 import"破坏，而破坏后只在缺少包的机器上暴露——即只在部署环境暴露，开发机永远看不出来。

### 4.4 干净环境复装

`pip install --dry-run --ignore-installed -r requirements-lock.txt` 与 `… torch --index-url …/cpu` 均解析成功（exit 0）。**如实说明**：这是解析层面的可复装验证，本机没有真的在空 venv 里跑一次完整下载安装（耗时与网络不可控），因此"锁定文件可在干净环境复装"目前是 resolution-level 证据，不是端到端证据。

---

## 5. 验证证据

### 5.1 测试

| 后端 | 结果 |
| --- | --- |
| JSON（默认） | **23/23 模块 PASS，273 条** |
| SQLite（`STORAGE_BACKEND=sqlite`） | **23/23 模块 PASS，273 条** |

新增 3 个模块：`test_backup` 15 条、`test_startup` 16 条、`test_optional_deps` 5 条（237 → 273）。`tests/tiers.py` 同步：`test_backup` = integration、`test_startup` = unit、`test_optional_deps` = unit。

### 5.2 静态检查

| 命令 | 结果 |
| --- | --- |
| `ruff check app` | 4 条既有基线（`anomaly.py:71` B905、`anomaly.py:129` B007、`pdf_extractor.py:190` B007、`rag_indexer.py:318` B905）——未新增 |
| `ruff check tests` | `All checks passed!`（新文件 3 处 I001 已用 `--select I001 --fix` 安全修复） |
| `ruff check scripts` | 2 条既有基线（`batch_verify.py:97` B905、`build_demo_video.py:56` F841）——未新增 |
| `mypy app` | **15 错误 / 6 文件 / 37 源文件**（源文件 +2：`backup.py`、`startup.py`；**错误数与 U7 持平 15**，新模块未引入新类型错误） |

### 5.3 演练与脚本

- `scripts/restore_drill.py`：6/6 PASS（数据见 2.5）。
- `scripts/license_audit.py`：49 分发、0 BLOCK（见 4.1）。
- `scripts/backup_chain.py verify` 已作为独立子命令可用（CI/运维单点校验，无需解包）。

---

## 6. TODO 全库扫描（`app/` + `tests/` + `scripts/`）

| 位置 | 内容 | 性质 |
| --- | --- | --- |
| `app/rate_limit.py:50` | `TODO[external-redis]`：跨进程计数器 | **真实待办**（U2 遗留） |
| `app/session_store.py:69` | `TODO[external-redis]`：多 worker 会话共享 | **真实待办**（U5.3 遗留） |
| `app/session_store.py:11` | docstring 指向同一 TODO | 引用，不计 |
| `app/observability.py:16` | docstring 指向同一 TODO | 引用，不计 |
| `app/startup.py:75` | 配置告警文案提到 `TODO[external-redis]` | 引用，不计（U8 新增，非待办） |
| `app/blockchain_util.py:3 / 13 / 248` | 指向 `TODO.md` 文件名 | 引用，不计 |

**真实待办仍为 2 条，U8 未新增任何 `TODO[external-*]` 占位。**

---

## 7. 未覆盖 / 已知边界（不粉饰）

1. **没有真的在干净环境跑一次完整安装**（4.4），只有解析级验证；也没有实际 `docker build`（本机无 Docker 守护进程可用性未验证），镜像分层是结构与顺序层面的改造。
2. **`INSTALL_ML=1` 路径未实测**：CPU torch + sentence-transformers + faiss 的镜像内组合没有构建过，降级路径（`INSTALL_ML=0`）才是被测过的路径。
3. **备份默认包含私钥**（`includes_private_keys=true`），`--exclude-keys` 是显式开关。部署口径（能否接受快照里带私钥、快照存哪里、访问控制）**未与用户确认**，报告只陈述现状。
4. **`/api/metrics` 仍在限流内**、且非 admin-only（U7 遗留的未决问题），U8 未改动。
5. **U7 的性能缺陷仍挂起**：`verify_hash` 每请求全链重放 + 单次验签 15 次 `read_info`（24.2 ms/op @链高 2），方案是 mtime 失效缓存 + 哈希→块高索引 + 链完整性短 TTL 缓存，**不在 U8 范围内**，未动。
6. **`mypy` 仍有 15 条既有错误 / 6 文件**，U8 只是没让它变多。
7. `docs/SBOM.*` 是**生成物**，依赖变更后必须重跑 `scripts/license_audit.py`，否则清单会过期（脚本没有内置"是否过期"的自检）。
8. 未做：备份包的**增量/差分**、快照上传/下载的目标存储（S3/R2）实现、多副本一致性校验。

---

## 8. 回滚

U8 的改动彼此独立，可按批回退：

- **U8.1**：删 `app/backup.py`、`scripts/restore_drill.py`、`tests/test_backup.py`；`git checkout -- scripts/backup_chain.py`；`app/chain_core.py` 的 `restore_snapshot_if_needed` 还原为"只挡 `..`/绝对路径"的版本（注意：那等于恢复 symlink 逃逸面）；`docs/DEPLOY.md` 删 1.1/1.2。
- **U8.2**：删 `app/startup.py`、`tests/test_startup.py`；`app/main.py` 的 `CONFIG_REPORT`/`_lifespan`/`checks.config` 段还原；`app/repository.py` 的 `close()`/`close_all()` 可保留（纯增量，不影响旧行为）。
- **U8.3**：`Dockerfile` 还原为单层（`torch` 无条件安装）版本；删 `.dockerignore`、`scripts/license_audit.py`、`docs/SBOM.*`、`tests/test_optional_deps.py`；`requirements-lock.txt` 头部注释还原。
- 三批都不触碰公共 API 签名，回滚不需要数据迁移；但 **U8.1 回滚会让启动恢复重新暴露 symlink 逃逸**，若生产已启用 `CHAIN_SNAPSHOT_URL`，建议只回滚 CLI 侧而保留 `chain_core` 的安全校验。

---

## 9. 下一批次建议

U8 收口了"部署可信度"这一层。按价值排序，下一批候选（任选其一，需用户决定）：

1. **U9-A 热点性能**（U7 遗留的真缺陷）：`verify_hash` 全链重放改为 mtime 失效缓存 + 哈希→块高索引 + 链完整性短 TTL 缓存，目标 P95 从 306 ms 降到 <20 ms（SQLite，8 线程）。
2. **U9-B 全局异常处理器**：U1 建了 5 个领域异常类，仍有 3 个没接到抛出点，`/api/verify/batch` 的 500 上限还是字面量——属于"半成品收尾"。
3. **U9-C 可观测性补全**：`/api/metrics` 定权（admin-only 还是公开放行）、`X-Request-ID` 进审计事件、审计分页与保留期。

**未做任何提交**：U0–U8 全部改动仍在工作区（最后一次提交 `11e7994`）。
