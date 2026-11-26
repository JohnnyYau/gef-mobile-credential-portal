# U2 验收报告 — 持久化抽象与 SQLite 落地

批次：U2（U2.1 仓储接口层 / U2.2 端点接线 / U2.3 撤销索引与后端隔离）
日期：2026-11-13
基线：U1 末（108 用例 / 12 模块全绿；ruff app 4 个既有 unsafe；mypy 16 错误 / 7 文件）

---

## 1. 批次结论

| 目标 | 状态 |
|---|---|
| 五个存储接口（`CredentialStore` 类族） | 完成，`app/repository.py` Protocol |
| JSON 实现逐字段对齐 | 完成，41 项一致性检查通过 |
| SQLite 实现（标准库 `sqlite3`） | 完成，6 表 2 索引 |
| 一次性迁移 + 迁移版本号 | 完成，幂等已验证 |
| 端点接线（`STORAGE_BACKEND` 开关） | 完成，四个模块委托仓储 |
| 撤销索引入库 | 完成，写穿 + 可重放重建 |
| `RateLimiter` 接口 + Redis 预留 | 完成（接口 + `TODO[external-redis]`），Redis 实现未做 |
| 双后端跑同一套测试 | 完成，json 12/12、sqlite 12/12 |
| 现有端点行为不变 | 完成，108 用例逐条通过 |

**未做（计划明确排除）**：分布式共识、外部托管数据库。

---

## 2. 改动清单

| 文件 | 状态 | 行数 | 内容 |
|---|---|---|---|
| `app/repository.py` | 新增 | 831 | 五接口 + JSON/SQLite 双实现 + 迁移 + 惰性取用器 |
| `app/apikeys.py` | 重写为门面 | 105 → 35 | 四个函数委托 `store("api_keys")` |
| `app/receipt_registry.py` | 重写为门面 | 66 → 26 | `register`/`get` 委托 |
| `app/public_log.py` | 重写为门面 | 82 → 40 | 保留 50 条窗口语义 |
| `app/notifier.py` | 改内部 | 107 → 82 | `_record`/`recent_notifications` 委托 |
| `app/issuance_service.py` | 改内部 | 78 → 99 | `revoke()` 写穿索引 + `rebuild_revocation_index()` |
| `app/rate_limit.py` | 增接口 | 37 → 55 | `RateLimiter` Protocol + Redis 预留 |
| `app/config.py` | 增配置 | +9 | `STORAGE_BACKEND`、`SQLITE_PATH`（随 `CHAIN_DIR` 派生） |
| `tests/test_extra2.py` | 改断言 | 1 处 | jsonl 存在性改为按后端判定 |

`main.py` 与全部端点：**零改动**。

---

## 3. 三个被真切踩到的坑

### 3.1 `CHAIN_DIR` 早绑定

`public_log.verification_log` 在模块导入时就实例化并锁定 `<chain-dir>/../`。测试靠"导入前注入 `CHAIN_DIR`"隔离，但少数模块会在导入后重绑。

若不处理，把存储实例也在导入期构造，就会固化旧路径，出现"测试全绿但读旧日志"的隐性错误。处理方式是把**全部实时路径**放进缓存键：

```python
if backend == "sqlite":
    return ("sqlite", str(cfg.SQLITE_PATH))
return ("json", str(cfg.BASE_DIR), str(cfg.CHAIN_DIR))
```

键随路径变化而变化，绑新目录自动换 bundle。实测 `reset_store_cache()` 后四类数据仍可读，证明缓存重建不丢数据。

### 3.2 `total()` 的窗口语义

`verification_log.total()` 原本返回 `deque` 长度（上限 50）。换成 `store.total()` 会变成**全量计数**（可能是 2000），Log 页数字会悄悄变大。改为 `min(store.total(), max_entries)`，`recent()` 同理取 `min(limit, max_entries)`。3 条→3、60 条→50、2000 条→50，三种情形均还原。

### 3.3 测试里有一条 JSON 后端专属断言

`test_extra2.test_public_log_persists_across_instances` 原断言 `log_path.exists()`。SQLite 后端本就不写 jsonl，必然失败（首轮 sqlite 全量 11/12）。

判断：这不是实现缺陷，而是断言绑定了实现细节。该用例的**真实意图**是"新实例能从持久存储读回"，与落在哪个介质无关。改法是把文件存在性检查限定在 json 后端，持久性断言（`fresh.recent()[-1]["hash_prefix"]`）两套后端都保留：

```python
if (cfg.STORAGE_BACKEND or "json").lower() == "json":
    self.assertTrue(log_path.exists())
fresh = public_log.PublicLog()
self.assertGreaterEqual(len(fresh.recent()), 1)
```

改动后 json 12/12、sqlite 12/12。**这是一处测试改动**，如实记录，未放宽其它断言。

---

## 4. 撤销索引：为什么只写穿、不用于判定

`revoke()` 在追加区块后，同一把链锁内 `upsert` 索引（height / revoked / reason / effective_at）。

**关键设计约束**：索引是**缓存**，链是唯一事实源。所有判定仍走 `revoked_records()`，因此索引缺失只会让查询变慢，**永远不会翻转 VERDICT**。这条约束决定了：

- 不需要在启动时重建（启动保持便宜）。补偿入口是显式函数 `rebuild_revocation_index()`，扫描全部 REVOKE 块重放。
- 不必担心迁移期索引与链不一致导致误判 —— 它不参与判定。

代价：json 后端会多出一个 `data/revocation-index.json` 落盘文件（此前没有）。已在 json 全量回归中确认无副作用（12/12）。

---

## 5. 双后端全量对照

| 后端 | 命令 | 结果 |
|---|---|---|
| 默认 json | `scripts\run_all_tests.py` | **12/12 模块绿** |
| SQLite | `$env:STORAGE_BACKEND="sqlite"; scripts\run_all_tests.py` | **12/12 模块绿** |

能跑通 sqlite 全量的关键：`SQLITE_PATH` 默认改为从 `CHAIN_DIR.parent` 派生。

```python
SQLITE_PATH = os.environ.get("SQLITE_PATH", str(CHAIN_DIR.parent / "portal.sqlite3"))
```

测试用 `isolated_chain_dir()` 给每个模块独立 `CHAIN_DIR`，于是每个模块自动拿到独立数据库，无需改 `run_all_tests.py`，也不会跨模块累积数据。生产默认 `CHAIN_DIR = data/demo-chain`，派生结果仍是 `data/portal.sqlite3`，与改动前同一位置。

---

## 6. 静态检查

| 项 | 结果 |
|---|---|
| `ruff check app` | **4 errors**，与基线逐条相同 |
| `mypy app` | **16 errors / 7 文件**，源文件 29，新增/改动模块零新增错误 |
| `ruff check tests` | All checks passed |

---

## 7. TODO 快照

| 标记 | 位置 | 状态 |
|---|---|---|
| `TODO[external-redis]` | `app/rate_limit.py` | 新增（计划要求预留） |
| `TODO[external-*]` 其它 | 全库 | 0 |
| `TODO`/`FIXME`/`HACK` 可执行待办 | `app/` 3 处（均为 docstring 引用历史文档名）、`scripts/` 0、`tests/` 0 | 无新增待办 |

既有 TODO 标记未被修改或删除。

---

## 8. 遗留

1. **Redis 限流实现未写**（仅接口 + 预留说明）。理由：引入 Redis 客户端会破坏零依赖安装；演示为单 Worker。
2. **连接池未做**：每操作短连接，演示规模可接受。
3. **多 Worker 未实测**：SQLite 模式为每模块独立库，未验证"多进程同时写同一库"的 WAL 竞争表现。
4. **`rawjsondocs` 明文索引仍未迁库**（计划内后续）。
5. **U1 遗留的 7 项**（全局异常处理器、领域异常替换抛出点、batch 500 字面量、README 模块清单等）不受 U2 影响，仍待后续批次。

---

## 9. 回滚

| 场景 | 操作 |
|---|---|
| 只想换回 JSON 存储 | `STORAGE_BACKEND=json`（默认值），代码无需回退 |
| 回退 U2 代码 | 删除 `app/repository.py`；`git checkout -- app/apikeys.py app/receipt_registry.py app/public_log.py app/notifier.py app/rate_limit.py app/issuance_service.py app/config.py tests/test_extra2.py` |
| 迁移数据回退 | SQLite 只读不写旧 JSON，旧文件原样保留，切回 json 即恢复原状 |

注意：U0/U1 改动也在同一批未提交工作区，按文件精确回退，勿整目录 `checkout`。

---

## 10. 下一批次

U3 — 鉴权与安全加固（角色模型、Key 生命周期、审计事件、密钥管理）。按批次红线，**不自动进入 U3**。

一处需要在 U3 前决策的事：审计事件走仓储层，会新增第六个存储。建议复用 `repository.py` 的三段式结构（接口 / JSON / SQLite），避免再开一个文件。
