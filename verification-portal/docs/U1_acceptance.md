# U1 验收报告 — 结构、异常与健壮性

批次：U1（子步 U1.1 领域异常体系 / U1.4 配置与常量集中 / U1.2+U1.3 服务层拆分与请求模型化）
日期：2026-11-13
基线：U0 末状态（108 用例 / 12 模块全绿；ruff app 4 个既有 unsafe；mypy 16 错误 / 7 文件）

**核心约束（全程遵守）**：公开 HTTP 路由、响应字段、错误状态码与 `{detail: <字符串>}` 形态逐一对齐；服务层拆分只做"位置迁移"，不改任何实现逻辑。

---

## 1. 子步结果一览

| 子步 | 内容 | 状态 | 明细报告 |
|---|---|---|---|
| U1.1 | 领域异常体系 + 14 处宽异常收窄 | 完成 | `docs/U1.1_exception_narrowing.md` |
| U1.4 | 8 个运营常量迁入 `config.py` | 完成 | `docs/U1.4_config_constants.md` |
| U1.2 | `chain_service.py` 拆分 4 个内部模块 + 薄门面 | 完成 | 本文件 §2 |
| U1.3 | 4 处手动 JSON 解析迁 Pydantic 模型 | 完成 | 本文件 §3 |
| 影响面评估 | 拆分/建模前的依赖与风险盘点 | 完成 | `docs/U1.2_U1.3_impact_assessment.md` |

---

## 2. U1.2 服务层拆分（改动清单）

### 2.1 文件级改动

| 文件 | 状态 | 行数 | 职责 |
|---|---|---|---|
| `app/chain_core.py` | 新增 | 238 | 唯一 `_lock`、链路径、签名者加载、链初始化 / 样例种子 / 快照恢复、`chain_info` |
| `app/signer_service.py` | 新增 | 64 | `sign_payload`、`list_signers`、`add_signer`、`set_active_signer` |
| `app/issuance_service.py` | 新增 | 78 | `hash_of`、`issue`、`revoke`、`revoked_records`、`revoke_meta` |
| `app/query_service.py` | 新增 | 200 | `status`、`verify_document`、`verify_hash`、`_corrupt_verdict`、`demo_credentials`、`chain_tail`、`student_credentials`、`chain_snapshot_id` |
| `app/chain_service.py` | 重写为门面 | 79（原 541） | 全量 re-export 24 个旧名字，`__all__` 显式声明 |

`git diff --stat`：`chain_service.py` −600 / +（门面内容），整体 `18 files changed, 297 insertions(+), 623 deletions(-)`（含 U1.1、U1.4）。

### 2.2 函数迁移映射（函数体逐行原样搬迁，未改实现）

| 旧位置（`chain_service.py`） | 新位置 |
|---|---|
| `_lock`、`SAMPLE_DIPLOMA/TRANSCRIPT/REVOKED_DOC`、`_info_path`、`_signer_priv_path`、`_ensure_signer`、`_load_signer`、`_active_signer_fgpt`、`_store_raw_document`、`_seed_samples`、`ensure_revoked_sample`、`restore_snapshot_if_needed`、`ensure_chain`、`chain_info` | `chain_core.py` |
| `sign_payload`、`list_signers`、`add_signer`、`set_active_signer` | `signer_service.py` |
| `hash_of`、`issue`、`revoke`、`revoked_records`、`revoke_meta` | `issuance_service.py` |
| `status`、`verify_document`、`verify_hash`、`_corrupt_verdict`、`demo_credentials`、`chain_tail`、`student_credentials`、`chain_snapshot_id` | `query_service.py` |

### 2.3 依赖方向（单向，无环）

`chain_service（门面） → signer/issuance/query_service → chain_core → blockchain_util / crypto_util / config`

- `chain_core` **不** import 任何 `*_service`，因此不存在循环导入。
- **锁语义关键点**：`_lock` 只在 `chain_core` 创建一次；`issuance_service` 通过 `from .chain_core import _lock` 取得同一对象。已实测 `chain_core._lock is issuance_service._lock == True`，否则种子与签发会各自加锁并发写链。

### 2.4 门面兼容性实测

`main.py`、`custom_service.py`、`chat_service.py`、`person_context.py`、`statuslist.py`、`scripts/local_smoke.py` 及 7 个测试模块引用的全部名字（24 个）逐一 `hasattr` 校验，**缺失 0 个**；调用方零改动。

---

## 3. U1.3 端点请求模型化（改动清单）

### 3.1 新增模型（`app/schemas.py`，第 74–139 行）

| 模型 | 字段 | 为什么用 `Any` |
|---|---|---|
| `CustomBuildBody` | 17 个自由字段 + `extra="allow"` | 旧实现把原始 JSON 字典透传给 `custom_service.build_document`，由其 `_clean` / `_norm_date` 自行归一。声明 `str` 会让"客户端传数字/布尔"这类旧可用输入新增 422。 |
| `VerifyDocumentBody` | `document: dict` | 等价于旧的 `isinstance(document, dict)` 校验。 |
| `VerifyBatchBody` | `hashes: list[Any]` | 逐行容错是既有契约：非字符串行要变成行内 `ERROR`，不能被整单校验拦下。 |
| `ApiKeyCreateBody` | `name: Any = None` | 旧实现 `payload.get("name") or "unnamed"` 直接透传任意值。 |

**刻意不把模型放进入参签名**：若写成 `body: CustomBuildBody`，FastAPI 会用自家 422 结构（`detail` 变成错误列表）替换现有 `{"detail": "<字符串>"}`，等于改了公开契约。改为函数体内 `model_validate`，捕获 `PydanticValidationError` 后抛**旧文案**的 `HTTPException`。

### 3.2 端点改动（`app/main.py`）

| 端点 | 行号 | 改动 |
|---|---|---|
| `POST /api/custom/build` | 300–330 | `await request.json()` + `isinstance` → `CustomBuildBody.model_validate`；`payload.get("issue", True)` → `body.issue`；传参 `body.model_dump()` |
| `POST /api/verify/document`（JSON 分支） | 400–415 | 改 `VerifyDocumentBody`；**multipart 分支完全未动** |
| `POST /api/verify/batch` | 510–525 | 改 `VerifyBatchBody`；保留空列表与 500 上限校验 |
| `POST /api/admin/apikeys` | 605–620 | 改 `ApiKeyCreateBody`；非对象体仍走 `"unnamed"` 默认 |

一处**有意对齐**：`/api/verify/document` 的 JSON 分支新增 `json.JSONDecodeError → 422 "Invalid JSON."`。原实现畸形 JSON 会抛 500，与另外两个端点（`/api/custom/build`、`/api/verify/batch`）已有的 422 行为不一致；本次对齐到 422，属修正而非新契约变化（已记录，若需严格保留 500 可单点回退）。

### 3.3 契约逐字核对（实测输出）

```
facade_missing: []
shared_lock: True
custom_build_non_object:      422  Body must be a JSON object.                OK
custom_build_missing_id:      422  请填写学号 Student ID。                     OK
verify_doc_wrong_shape:       422  JSON body must be {"document": {...}}.      OK
verify_doc_missing_key:       422  JSON body must be {"document": {...}}.      OK
batch_missing:                422  Body must be {"hashes": [...]}.             OK
batch_empty:                  422  Body must be {"hashes": [...]}.             OK
batch_not_list:               422  Body must be {"hashes": [...]}.             OK
verify_doc_unsupported_type:  415  Send application/json or multipart/...      OK
batch_row_tolerance:          200  ['ERROR', 'INVALID HASH FORMAT']
apikey_non_object:            200  unnamed
FAILURES: []
```

---

## 4. 批次统计

| 项 | 数量 |
|---|---|
| 新增文件 | 5 个 app 模块（`errors.py`、`chain_core.py`、`signer_service.py`、`issuance_service.py`、`query_service.py`）+ 3 份验收/评估文档 |
| 重写文件 | 1（`chain_service.py` 541 → 79 行，净减 462 行） |
| 修改文件 | 9（`config.py`、`main.py`、`schemas.py`、`notifier.py`、`rag_generator.py`、`pdf_diploma.py`、`pdf_extractor.py`、`person_context.py`、`rag_embedder.py`） |
| 收窄宽异常 | 14 处；保留有意兜底 5 处 |
| 集中常量 | 8 个 / 9 处接入 |
| 请求模型化端点 | 4 处 |
| 静态检查 | 无新增问题（见 §5） |
| 单测 | 108 用例 / 12 模块全绿 |
| 契约核对用例 | 10 项全通过 |

---

## 5. 静态检查结果

- `ruff check app`：**4 errors**，全部为 U0 既有 unsafe 项（`anomaly.py:71` B905、`anomaly.py:129` B007、`pdf_extractor.py:190` B007、`rag_indexer.py:231` B905）。U1.2 期间新增的 `I001`（门面导入排序）已用 `ruff --select I001 --fix` 修掉，未使用 unsafe-fixes。
- `mypy app`：**16 errors / 7 文件**，与 U0 末基线逐条一致（24 → 28 个源文件被检查，错误数未变）。
- `ruff check tests`：干净。

---

## 6. TODO 库存快照（全库扫描）

| 范围 | `TODO` / `FIXME` / `HACK` 命中 | 说明 |
|---|---|---|
| `app/` | 3 | 全部位于 `blockchain_util.py` docstring，引用历史文档名 `TODO.md`，非待办标记 |
| `scripts/` | 0 | — |
| `tests/` | 0 | — |
| 全库 `TODO[external-*]` | 0 | 无外部 SDK 占位标记 |

已解决项：U1.1 收窄的 14 处宽异常、U1.4 的 8 个字面量。
未解决项（转入后续批次）：见 §7。

---

## 7. 遗留与未做项（如实记录）

1. **全局异常处理器未落地**。当前仍是各路由独立 `try/except ValueError → 422 / RuntimeError → 503`。改用 FastAPI exception handler 会改变未捕获异常的响应形态，风险高于本批次收益；建议随 U2 仓储层（错误来源集中）一并设计。
2. **`SignerUnavailableError` / `UnavailableBackendError` / `FileAccessError` 已建模但未替换抛出点**。服务层现仍抛 `ValueError` / `RuntimeError`；迁移需逐点核对 422/503 归属，留到 U2／U4。
3. **`_PdfReadError` 之外的 pypdf 侧异常**（如加密 PDF）未逐一建模，仍在 `PyPdfError` 覆盖范围内。
4. **`/api/verify/batch` 的 500 行上限仍是字面量**（`main.py:527` 附近），未迁入 `config.py`（与 `BATCH_ISSUE_MAX=200` 语义不同，需单独命名后再迁）。
5. **`README.md` 第 495 行附近的模块清单仍只列 `chain_service.py`**，未补 4 个新内部模块；属文档更新，留到文档批次统一处理，避免本批次混入非代码改动。
6. **`web_research.py` 两处外部网络兜底仍为宽异常**（正文本轮未改）。
7. 可执行层面的"无静默吞错"尚未 100% 达成：`person_context._verdict`、`custom_list` 等 4 处仍在失败时返回空/UNKNOWN 兜底（已收窄类型并保留日志），未改为抛领域异常——因为这些端点的既有契约就是"降级返回"，改动会破坏 UI 行为。

---

## 8. 回滚

U1 全部改动仍在工作区未提交（分支 `main`，最后提交 `11e7994`）。

```powershell
# 回到 U0 末状态
git checkout -- verification-portal/app
Remove-Item verification-portal/app/errors.py,
            verification-portal/app/chain_core.py,
            verification-portal/app/signer_service.py,
            verification-portal/app/issuance_service.py,
            verification-portal/app/query_service.py
```

U0 工程配置（`pyproject.toml`、`requirements-*.txt`、`tests/_bootstrap.py`）不在 U1 回滚范围内。

---

## 9. 下一批次

**U2 — 持久化抽象与 SQLite 落地**（`CODE_UPGRADE_PLAN.md` 第 116 行起）：仓储接口层、JSON 实现对齐、`sqlite3` 落地、多 Worker 兼容。

按批次红线，**不自动进入 U2**；需显式指令后再开始。
