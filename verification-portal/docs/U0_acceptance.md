# U0 验收报告 — 质量门禁与测试基线

- 批次：U0（U0.0 基线核对 / U0.1 工程配置 / U0.2 测试夹具抽取 / U0.3 类型标注基线）
- 环境：Windows 本地，`verification-portal/`，venv Python 3.13.16（Dockerfile 目标 `python:3.12-slim`，版本一致性留待 U8 部署批次核对）
- 执行日期：2026-11-13
- 红线确认：未删除/改名任何 FastAPI 路由、请求响应字段、`schemas.py` 模型字段或服务层对外函数签名；未改动六项检查判定语义。

---

## 1. 基线 → 结果对照

| 维度 | U0 前基线 | U0 后 | 说明 |
|---|---|---|---|
| 测试用例 | 108 用例 / 12 模块 | 108 用例 / 12 模块，全绿 | 用例数零增减；未新增行为测试 |
| ruff（tests/） | 含重复样板与未用导入 | `All checks passed!` | 测试侧 lint 干净 |
| ruff（app/） | 60 问题（48 安全可自动修复） | 4 个 unsafe 项，留 U1 | 未使用 `--unsafe-fixes` |
| mypy | 33 错误 / 7 文件 | 16 错误 / 7 文件 | 只降不升；relaxed 模式保持 |
| 类型标注 | 190 函数，53 个带返回类型（约 28%） | `blockchain_util.py` 22/22 函数补全标注；全仓 `->` 出现次数 53 → 91（正则口径，含局部标注） | 其余模块按 U0.3 顺序在后续批次补 |
| 工程配置 | 无 pyproject / ruff / mypy / pytest 配置 | 新增 `pyproject.toml`、`requirements-dev.txt`、`requirements-lock.txt` | 见下 |
| 测试样板 | 12 模块各自 `mkdtemp + CHAIN_DIR` | 11 个模块迁入共享引导；1 个子进程模块保留自身临时目录 | 见 §4 偏差说明 |

## 2. 改动文件清单

### 2.1 新增文件

| 路径 | 作用 |
|---|---|
| `verification-portal/pyproject.toml` | pytest 路径/警告过滤；ruff（line-length 100、target py312、规则 E/F/I/B/UP/Q、忽略 E501）；mypy relaxed（`check_untyped_defs=false`、`no_implicit_optional`、`ignore_missing_imports`） |
| `verification-portal/requirements-dev.txt` | `-r requirements.txt` + pytest / ruff / mypy / hypothesis（均 MIT/BSD 类） |
| `verification-portal/requirements-lock.txt` | 本机实测通过的直接依赖版本钉版；传递依赖与完整 SBOM 留 U8 |
| `verification-portal/tests/_bootstrap.py` | `isolated_chain_dir(prefix, **env)`：建临时链目录、设 `CHAIN_DIR`、按需设置/弹出环境变量；`env` 值传 `None` 表示弹出变量 |

### 2.2 本批次修改文件（类型标注 / 夹具迁移）

| 路径 | 改动区域 | 内容 |
|---|---|---|
| `app/blockchain_util.py` | 导入 27–38；签名 47–537 | 22 个函数补参数/返回类型；局部 `result`/`status` 字典显式 `dict[str, Any]`；删除未使用的 `payload_hash` 局部变量；兼容导入加 `# type: ignore[no-redef]` |
| `app/main.py` | 批量核验端点 514–558 | `results: list[dict[str, object]]`、`entry: dict[str, object]` 显式放宽，消除字典类型过窄的 dict-item 报错；行为不变 |
| `tests/test_api.py` | 顶部导入与链目录样板 | 改用 `isolated_chain_dir`；移除未用 `os`/`tempfile` 导入 |
| `tests/test_custom.py` | 顶部样板 | 同上；保留 `CUSTOM_OUTPUT_DIR` 临时目录设置 |
| `tests/test_extra2.py` | 顶部样板 + 133 行 | 夹具迁移；未用局部变量 `info` 改为保留调用、丢弃赋值 |
| `tests/test_features.py` | 顶部样板 | 夹具迁移 |
| `tests/test_hardening.py` | 顶部样板 | 夹具迁移；保留 `os`（正文 `os.path.join`） |
| `tests/test_person.py` | 顶部样板 | 夹具迁移；移除未用 `os`/`tempfile` |
| `tests/test_rag.py` | 顶部样板 | 夹具迁移；`DEEPSEEK_API_KEY`/`OLLAMA_BASE_URL` 以 `None` 弹出 |
| `tests/test_employer_pack.py` | `setUpModule` | 链目录改走 `isolated_chain_dir`；保留模块重载与私有模式恢复逻辑 |
| `tests/test_issue_batch.py` | `setUpModule` | 同上 |
| `tests/test_pdf_extractor.py` | `setUpModule` | 同上 |
| `tests/test_public_mode.py` | `setUpModule` | 同上；保留 `PUBLIC_MODE=1`、`APP_VERSION=6.0.0` 设置 |

### 2.3 U0.1 ruff 安全自动修复触及的既有文件（仅 lint 层，无行为变更）

`app/chat_service.py`、`app/crypto_util.py`、`app/custom_service.py`、`app/pdf_diploma.py`、`app/pdf_extractor.py`、`app/public_log.py`、`app/rag_indexer.py`、`app/receipt_registry.py`、`app/schemas.py`、`app/statuslist.py`、`scripts/backup_chain.py`、`scripts/batch_verify.py`、`scripts/build_demo_video.py`、`scripts/local_smoke.py`。
完整逐行 diff 以 `git diff` 为准；本批次未对上述文件做逻辑改动。

## 3. 接口兼容性确认

- 路由路径、请求/响应 JSON 字段、`schemas.py` 模型字段：未改动。
- 服务层对外函数名与签名：未改动；`blockchain_util.py` 仅补标注，参数名与默认值保持原样。
- 测试断言与用例数：108 条全部保留，逐条通过。

## 4. 测试结果

命令（subprocess 逐模块隔离，避免共享全局链目录/签发方注册表互相污染）：

```
.venv\Scripts\python.exe scripts\run_all_tests.py
```

结果：**12/12 模块 PASS**，用例计数与基线一致：

| 模块 | 用例数 |
|---|---|
| test_api | 16 |
| test_custom | 8 |
| test_employer_pack | 9 |
| test_extra2 | 18 |
| test_features | 8 |
| test_hardening | 7 |
| test_issue_batch | 5 |
| test_pdf_extractor | 6 |
| test_person | 13 |
| test_public_mode | 6 |
| test_rag | 10 |
| test_restart_persistence | 2 |
| **合计** | **108** |

### 4.1 偏差说明（与计划 U0.2 的差异）

计划原拟提供 pytest `conftest.py` 的 `isolated_chain` / `client` fixture。**未采用**，原因是实测约束：`app.config` 在**模块导入时**捕获 `CHAIN_DIR`，而 pytest fixture 在导入之后才运行，无法在导入前注入环境变量；强行 per-test 夹具会破坏现有模块隔离。

落地替代：新增 `tests/_bootstrap.py` 共享引导函数，消除重复的 `mkdtemp + os.environ["CHAIN_DIR"]` 样板；真正的 per-test fixture 迁移推迟到 U1/U2 配置改为惰性读取之后。`test_restart_persistence.py` 起真实 uvicorn 子进程，保留自身 `tempfile.TemporaryDirectory`，未迁移。

## 5. 静态检查结果

### 5.1 ruff

- `ruff check tests`：**All checks passed!**
- `ruff check app`：**4 个 unsafe 项**，均留 U1 处理（本批次未启用 unsafe 修复）：

| 位置 | 规则 | 说明 |
|---|---|---|
| `app/anomaly.py:71` | B905 | `zip(series, pred)` 缺 `strict=` |
| `app/anomaly.py:129` | B007 | 未使用循环变量 `key` |
| `app/pdf_extractor.py:188` | B007 | 未使用循环变量 `conf` |
| `app/rag_indexer.py:231` | B905 | `zip(scores[0], indexes[0])` 缺 `strict=` |

### 5.2 mypy（relaxed 基线）

- 基线：33 错误 / 7 文件 → 现在：**16 错误 / 7 文件**。
- 剩余错误按类别（U1 收窄异常/补标注时一并处理）：
  - `union-attr`：`UploadFile | str` 联合类型访问 `.close` / `.filename`（`main.py:411, 417, 473`）。
  - `arg-type`：`register` / `hash_of` 收到 `Any | None`（`main.py:360, 376, 428, 537`；`chain_service.py:387`）。
  - `assignment` / `call-overload`：`crypto_util.py:32`、`statuslist.py:55`、`pdf_diploma.py:30,195,198`、`pdf_extractor.py:150`。
  - `var-annotated`：`person_context.py:19` `_sessions`、`pdf_extractor.py:169` `doc` 缺容器标注。
- `blockchain_util.py` 单独 mypy 复查：本模块无错误（仅剩跨文件 `crypto_util.py:32` 既有项）。

### 5.3 标注覆盖现状（正则口径，`->` 出现次数 / `def` 数）

`blockchain_util.py` 22/22；缺口仍集中在 `main.py`（40 def / 8）、`rag_indexer.py`（12 / 0）、`person_context.py`（8 / 0）、`rag_embedder.py`（4 / 0）、`rag_generator.py`（8 / 0）、`web_research.py`（5 / 0），按 U0.3 优先级在后续批次补全。

## 6. 已知遗留与占位

- 未引入新外部 SDK；无新增 `TODO[external-xxx]`。
- 可选重型 ML 依赖（`sentence-transformers`、`faiss-cpu`、`scikit-learn`）未装入本离线 venv，门户走哈希嵌入 / numpy 检索 / 内置启发式兜底；`requirements-lock.txt` 未钉版这三项，待安装并测试后再纳入。
- 传递依赖完整冻结、许可证 SBOM、Python 版本（venv 3.13 vs Dockerfile 3.12）一致性：归 U8 部署与依赖治理。
- 宽异常 `except Exception`（基线 19 处 / 10 文件）本批次未收窄，归 U1.1。

## 7. 回滚方式

- 配置/夹具为增量新增：删除 `pyproject.toml`、`requirements-dev.txt`、`requirements-lock.txt`、`tests/_bootstrap.py`，并将 11 个测试模块顶部样板还原即可回到 U0 前状态。
- 代码改动均为标注与类型声明放宽，无逻辑分支变更；如需整体回退，使用批次前的 git 提交点 `11e7994`（未跟踪文件直接移除）。
- 本批次未提交 git；改动留在工作区，待确认后再按批次单独提交。

## 8. 下一步（不自动进入）

按计划 U1「结构、异常与健壮性」启动前需人工确认：U0 报告口径与遗留项无异议。U1 首批建议 U1.1 领域异常体系 + 19 处宽异常收窄。
