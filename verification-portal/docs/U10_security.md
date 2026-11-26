# U10 批次验收报告 · 签名私钥落盘加密 + U1 三遗留收口（计划外批次）

> 本批次仍不在 `CODE_UPGRADE_PLAN.md` 的 U0–U8 编号内，是按用户「繼續」推进的第 10 批。取 U9 报告 §10 的建议第 1 条（私钥口令加密，遗留里安全缺口最大的一项）为主项，顺带清掉 U1 遗留的三件小事：3 个已建模异常类从未被抛出、`/api/verify/batch` 的 500 上限是字面量、`README.md` 的模块清单停在 10 个模块。

## 1. 一句话结论

私钥加密**做成可选开关，默认行为字节级不变**：`GEF_KEY_PASSPHRASE` 不设时仍是历史的明文 PKCS#8（所有既有部署、脚本、demo 链都不受影响）；设了之后新生成的密钥直接加密、盘上已有的明文密钥在首次加载时**原地重新加密**，口令不匹配则**报错停机式拒绝**而不是悄悄换钥（换钥会让链上已签的每个块签名失效）。实测：全新链 + 口令 → 密钥文件含 `ENCRYPTED PRIVATE KEY`，`POST /api/issue` 200、`GET /api/verify/{hash}` 返回 `VALID ON CHAIN`；`/healthz` 的配置检查对「没设口令却有明文密钥」「设了口令但密钥还没迁移」两种情况各给一条警告。

## 2. 改动文件清单（路径 + 行号）

### 2.1 `app/config.py`

| 行 | 改动 |
| --- | --- |
| 98 | 新增 `MAX_BATCH_DOCUMENTS: int = 500`（原来硬编码在 `main.py`） |
| 100–105 | 新增 `SIGNER_KEY_PASSPHRASE`（读 `GEF_KEY_PASSPHRASE`，默认空串 = 明文） |

### 2.2 `app/chain_core.py`

| 行 | 改动 |
| --- | --- |
| 38 | 新增模块级 `logger`（迁移时打一条 warning） |
| 109–115 | 新增 `_passphrase()`：**调用时**从 `cfg` 读，不在 import 时固化（部署可在启动后注入、测试可逐例翻转） |
| 118–128 | 新增 `_looks_encrypted(path)`：只看 PEM 头 64 字节，不做解密尝试——口令我打错时也能正确判断"这文件是加密的" |
| 131–164 | 新增 `load_private_key(path, algo)`：三分支见 §3.2 |
| 167–178 | `_ensure_signer()` 生成的新钥按口令加密写盘 |
| 181–202 | `_load_signer()` 改走 `load_private_key`；两处 `RuntimeError` 换成 `SignerUnavailableError`（子类仍是 `RuntimeError`，端点 503 映射不变）；加载前若「设了口令但文件仍明文」先打 warning |
| 216–230 | `_store_raw_document()` 的 `OSError` 包成 `FileAccessError`（`project_docs` 写失败 vs 链数据损坏，可区分了） |

### 2.3 `app/signer_service.py`

| 行 | 改动 |
| --- | --- |
| 13 | 导入 `_passphrase` |
| 49–50 | `add_signer()` 生成的新密钥同样按口令加密 |

### 2.4 `app/rag_generator.py`（第三类异常接线）

| 行 | 改动 |
| --- | --- |
| 28 | 导入 `UnavailableBackendError` |
| 66–90 | `_deepseek()` 把 `httpx.HTTPError` / 结构错包成 `UnavailableBackendError` |
| 92–109 | `_ollama()` 同上 |
| 364 / 375 | 两个降级分支显式 `except UnavailableBackendError`（仍降级到下一个后端，**HTTP 契约不变**） |

### 2.5 `app/startup.py`

| 行 | 改动 |
| --- | --- |
| 88–108 | `validate_config()` 新增密钥落盘检查：未设口令且有 `.priv.pem` → 警告（列出文件数）；设了口令但有明文 key → 警告（列出文件名）。都只报警不 fatal |

### 2.6 `app/main.py`

| 行 | 改动 |
| --- | --- |
| 742 / 755–758 | `POST /api/verify/batch` 的上限从字面量 500 改为 `cfg.MAX_BATCH_DOCUMENTS`（错误文案随常量生成，行为不变） |

### 2.7 文档

| 文件 | 改动 |
| --- | --- |
| `README.md` | 环境变量表补 `GEF_KEY_PASSPHRASE`（含迁移与"不换钥"语义）；`## Layout` 重写为当前真实的 **37 个 app 模块 / 26+1 个测试模块 / 三层 Dockerfile**（原来写的是 10 个模块时代的清单） |
| `docs/DEPLOY.md` §5 | 补「Signer key at rest」四段：加密格式、迁移时机与备份提醒、口令不匹配即拒绝签发、`/healthz` 警告 |

### 2.8 新增测试 `tests/test_key_at_rest.py`（9 条）

| 用例 | 断言的内容 |
| --- | --- |
| `test_plaintext_by_default` | 不设口令 → 密钥文件里没有 `ENCRYPTED PRIVATE KEY`（默认行为未变） |
| `test_passphrase_encrypts_a_new_key` | 设口令后新钥落盘即加密，且能正常加载 |
| `test_existing_plaintext_key_is_re_encrypted_on_first_load` | 明文 → 首次 `_load_signer` 后文件加密；**私钥数值不变**（`private_value` 相等），且新文件确实需要口令（无口令加载抛 `TypeError`） |
| `test_wrong_passphrase_fails_loudly_and_keeps_the_key` | 抛 `SignerUnavailableError`、消息含 `GEF_KEY_PASSPHRASE`、密钥文件数仍为 1、链高不变（没有偷偷换钥） |
| `test_correct_passphrase_signs_normally_after_migration` | 迁移后能用同一条密钥追加块，`fetch_status` 报 issued |
| `test_issue_endpoint_shape_is_unchanged_with_a_passphrase` | `issuance_service.issue()` 返回结构不变，签发结果在链上可查 |
| `test_unencrypted_key_without_passphrase_is_reported` | 启动检查给出 "GEF_KEY_PASSPHRASE is unset … unencrypted" 警告，且不是 fatal |
| `test_passphrase_with_plaintext_key_is_reported` | 启动检查给出 "re-encrypted on first load" 警告 |
| `test_encrypted_key_and_passphrase_is_quiet` | 已加密 + 有口令 → 相关警告为空 |
| `tests/tiers.py` / `scripts/run_all_tests.py` | 新模块分层 `integration`，`MODULES` 26 → 27 |

## 3. 设计取舍

### 3.1 为什么是开关而不是强制

强制加密会让**所有既有部署**（含本机 demo 链、`scripts/*`、`tests/*` 里直接 `fetch_privkey(...None)` 的代码）一次性失效，属于"为安全改进砸掉可用性"。默认关闭 + 部署侧一行环境变量打开，是这批唯一能不破坏 26 个既有测试模块的做法；代价是"没设口令 = 仍然明文"，所以启动检查必须把这件事说出来（见 §2.5）。

### 3.2 加载的三条分支

```
口令已设 + 文件已加密  → 用口令解密
口令已设 + 文件仍明文  → 无口令解出 → 立刻用口令原地重写（迁移）
口令已设 + 解密失败    → SignerUnavailableError，拒绝签发
```

第三条是整批里最关键的取舍：`_ensure_signer()` 只在"信任签名者注册表为空"时才生成新钥，而注册表非空时加载失败**不会**触发重新生成——所以口令输错的结果是"发不出凭证"（503），不是"悄悄生成一把新钥、从此所有旧块签名校验失败"。测试 `test_wrong_passphrase_fails_loudly_and_keeps_the_key` 把这条锁住了。

### 3.3 加密参数

走 `cryptography` 的 `serialization.BestAvailableEncryption`（PKCS#8 PBES2：scrypt + AES-256-CBC），**没有自己写 KDF/AEAD**。这是 U0 就定下的原则：密码学原语只用库提供的标准实现，改的是"调不调它"，不是"怎么实现它"。

### 3.4 与 U9-B 的一致性

`audit.record()` 那次不改签名是因为公共 API 冻结；这次同样没有动 `crypto_util.save_privkey/fetch_privkey`（它们本来就有 `password` 参数，只是调用方一直传 `None`）——所以整批**没有一处公共签名变化**，改的全是调用点与新增的内部辅助函数。

## 4. 验证证据

口径：Windows 本地、venv Python 3.13.16、`scripts/run_all_tests.py` 逐模块 subprocess 隔离。

- 全量回归：**JSON 后端 27/27 模块、309 条全绿**；**SQLite 后端（`STORAGE_BACKEND=sqlite`）同样 27/27、309 条全绿**（U9 后 26 模块 300 条 → 本批 +1 模块 +9 条）。
- `ruff app`：**4 条既有基线**（`anomaly.py:71` B905、`anomaly.py:129` B007、`pdf_extractor.py:190` B007、`rag_indexer.py:318` B905），未新增。
- `ruff tests`：**All checks passed!**
- `ruff scripts`：**2 条既有基线**（`batch_verify.py:97` B905、`build_demo_video.py:56` F841），未新增。
- `mypy app`：**15 错误 / 6 文件 / 37 源文件**，与 U8/U9 基线完全一致。

端到端（全新临时链 `CHAIN_DIR=%TEMP%\gef26-u10e2e\chain`，`GEF_KEY_PASSPHRASE=e2e-passphrase`，同进程 TestClient）：

```
key file: signer-99081c068e12d55960fe4836.priv.pem encrypted: True
issue: 200 hash: GFiY4d67yoi8X4wm
verify: 200 verdict: VALID ON CHAIN
healthz config: {'fatal': 0, 'warnings': 0}
```

真实 demo 链（`data/demo-chain`，4 把历史明文密钥，未设口令）回归确认：

```
active 9c:32:51:ba:
warnings ['GEF_KEY_PASSPHRASE is unset and 4 signer private key file(s) are
          stored unencrypted under ...\data\demo-chain\keys — set
          GEF_KEY_PASSPHRASE to encrypt them at rest']
```

即：**真实演示链未被本批改动影响**，只是启动检查多了一条如实的警告。

## 5. U1 三遗留收口（本批同批做掉）

| 遗留 | 处理 | 位置 |
| --- | --- | --- |
| 3 个已建模异常类从未被抛出 | `SignerUnavailableError` → 签名者/密钥缺失、口令不匹配；`UnavailableBackendError` → DeepSeek/Ollama 配置了但不通；`FileAccessError` → rawjson 文档写盘失败 | `chain_core.py` L156/L159/L186/L194/L226、`rag_generator.py` L86/L105 |
| `/api/verify/batch` 500 上限是字面量 | 提常量化 | `config.py:98`、`main.py:755` |
| `README.md` 模块清单过期 | 重写 Layout 为 37 模块现状 | `README.md` §Layout |

三个异常类的父类决定了端点映射不变：`SignerUnavailableError` ⊂ `RuntimeError`（→503）、`UnavailableBackendError` ⊂ `RuntimeError`（被降级分支吸收，不外露）、`FileAccessError` ⊂ `OSError`（原本就未捕获 → 500，与之前一致）。

## 6. TODO 全库扫描（U10 批次后）

| 分组 | 命中 | 性质 |
| --- | --- | --- |
| `app/blockchain_util.py:3/13/339` | 3 | **引用** `TODO.md` 文件名，不是待办 |
| `app/rate_limit.py:50` | 1 | **真实待办** `TODO[external-redis]`（多 worker 共享计数） |
| `app/session_store.py:69` | 1 | **真实待办** `TODO[external-redis]`（多 worker 会话共享） |
| `app/session_store.py:11`、`app/observability.py:16`、`app/startup.py:75` | 3 | **引用**上述两条 external 待办 |
| 合计 | 8 | 真实待办仍为 **2 条**；本批**未新增、未删除**任何 TODO |

## 7. 未覆盖 / 遗留

1. **密钥迁移不是原子的**。原地重写用 `save_privkey`（普通 `open(...,"wb")`），没有 `.tmp` + `os.replace`。若恰好在写入过程中断电，明文文件已被截断、加密内容未落全 → 密钥损坏（链上块仍在，但再也签不出新块）。当前只在"首次带口令启动"这一刻触发；要么接受，要么后续把 `crypto_util.save_privkey` 改成原子写（会动公共模块，本批未做）。
2. **口令来自环境变量**，会出现在进程环境、可能落进 `docker inspect` / 崩溃转储。真隔离需要 KMS/HSM 或 systemd credential 一类，不在本批。
3. `SIGNER_KEY_PASSPHRASE` 在 `config.py` 里是 **import 时从 `os.environ` 读一次**；`chain_core._passphrase()` 每次调用读 `cfg` 属性，所以同进程内翻转 `cfg` 有效、改 `os.environ` 无效。部署侧在启动前设置即可，但热改环境变量不会生效——这是故意的（避免运行中口令漂移）。
4. 已有明文密钥在**没有口令**的部署里依然是明文，本批只是把这件事从"没人知道"变成"启动日志会警告"。要不要把 U8 备份包的 `includes_private_keys` 口径与口令联动，属部署策略，待用户拍板。
5. U9 报告 §10 的其余建议未动：回执/审计/公开日志统一落 SQLite、块目录内容摘要替代 mtime 指纹。
6. U7 遗留仍未动：`rawjsondocs` 明文索引迁库、真 LLM 联调、前端渲染 `generation.*`、无浏览器 E2E、未加 CSP、`/api/metrics` 权限与 `_EXEMPT_PATHS`。

## 8. 回滚

改动集中在 6 个源文件 + 1 个新测试模块 + 3 份文档，无数据格式迁移（**唯一的盘上变化是密钥文件加密**）：

- 关掉加密：删掉 `GEF_KEY_PASSPHRASE` 环境变量即可——但**已被加密的密钥不能在没有口令的情况下加载**（会报 `SignerUnavailableError`）。要真正回退必须先用口令解出密钥、再用无口令方式另存：`crypto_util.save_privkey(priv, algo, path, None)`。
- 代码回滚：`chain_core.py` 删掉 L109–164 与 L199–201，`_ensure_signer` 的 `save_privkey` 参数回 `None`，`_load_signer` 回到 `fetch_privkey(path, None)` + `RuntimeError`；`startup.py` 删 L88–108；`config.py` 删 L98/L100–105；`main.py:755` 回字面量 500。
- 测试模块 `tests/test_key_at_rest.py` 可整体删除，`tiers.py` / `run_all_tests.py` 各删一行即回到 26 模块。
