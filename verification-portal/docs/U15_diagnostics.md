# U15 — 诊断与运维收口（从一条坏链说起）

这一轮的起点不是清单，而是我自己写的一个冒烟脚本。写它的原因是上一轮
所有验证都靠「跑测试 + 手工 curl」，没有一件东西能在重启后花十秒回答
「这个实例还好吗」。脚本第一版写完，第一次对 8013 跑，就打了三次 FAIL，
其中一次不是脚本的问题。

## 1. 发现：演示链上有一个无法验证的块

`GET /api/verify/{hash}` 返回 `verdict: INVALID`、`chain_integrity: false`。
在此之前，U13/U14 的每次实测都是 `VALID`。逐块查下来：

```
block 12  checks: signatures=False
          signature_problems: ['untrusted signer fingerprint 9e:72:ec:56:4b:07:41...']
```

块 12 是由一个**已经不在 `info.yaml.trusted_signers` 里**的签名者签的，它的
公钥也不在 `keys/` 里（四个现存签名者的指纹都对不上 9e:72）。这意味着：

- 该块的签名**无法验证**（没有公钥），不是「验证了但不可信」；
- `verify_chain()` 整体为 false，而 `chain_integrity` 是六项检查之一；
- 因此**每一个**凭证的 verdict 都变成 INVALID，包括 seed 时就签发的那本。

根因在数据层，不在代码：U12/U13 的多签名者实验注册过这个签名者，后来的
某次链目录替换 / 快照恢复只带回了旧 `info.yaml`，块却留下了。私钥与公钥
在项目里都已不存在（全仓搜 `9e:72:ec:56` 与所有 `.pem` 均无），所以这条块
在密码学上已经不可恢复。

**处理**（有损，但已留证据）：

- 整条旧链移到 `verification-portal/data/demo-chain-broken-20261120/`，
  连同旧的 `keys/`、`info.yaml`、块文件一起保留，不删；
- 让实例按默认流程重新 seed（height 2：diploma + transcript，1 个签名者）；
- 补回演示要素：注册第二个签名者（`REGISTRAR OFFICE`，RSA-PSS 2048）、
  签发一份 `22990001` 再撤销（`DEMO SAMPLE: issued by mistake`，块 3 / 4），
  用来演示 REVOKED 与 U14 的 PDF 红带；重新 mint 学号 22000000 的持证人链接。

重建后：`verify → VALID ON CHAIN`、`integrity=true`、height 4、2 signers。
`data/` 本来就不进提交包（`build_package.py` 的 `EXCLUDE_DIRS`），所以包里
的链一直是首启动重新生成的干净链，这个坑只在本地演示实例上存在。

## 2. 代码：让「链坏了」一眼可见

一个坏块能让全部判定失效，却在 `/healthz` 里什么都不显示——这是最响的故障
配最静的信号。

- `main.chain_integrity()` — 跑 `verify_chain()`，返回
  `{"ok": bool, "bad_blocks": [height...]}`。按「链目录 + 高度」缓存 30 秒，
  高度一变立刻重算，所以不会因为每次 verify 都全链扫描而变慢。
- `/healthz` 的 `checks.chain.integrity` 输出该结果；`ok=false` 会把顶层
  `status` 从 `ok` 变成 `degraded`。
- `/api/version` 的 `chain.integrity` 也带同一份结果，公开页在 `ok=false` 时
  往页首插一条红条：「所有判定都会显示 INVALID，问题在服务端而不是这张凭证」。
  访问者看到 INVALID 时第一反应是怀疑持证人造假，这条红条把责任放回正确的位置。

现在这类问题在 `curl /healthz` 一眼可见，不用等访客先发现 INVALID。

## 3. 代码：`uptime_s` 是 epoch 而不是秒

```
"uptime_s": 1795186022.7
```

`_started_at` 保存的是 `time.time()`，而返回时直接 round 了它。任何拿
`uptime_s` 做重启判断的脚本都会读到 ≈1.7e9。改为 `time.time() - _started_at`。
冒烟脚本里加了一条专门的断言（`0 <= uptime < 一年秒数`），防止再退回去。

## 4. 代码：撤销扫描的缓存

`revoked_records()` 逐块遍历全链，而它有四个调用点：单条 verify、文档 verify、
批量 verify（最多 500 条）、PDF 渲染。500 条批量 = 500 次全链扫描。

加 5 秒 / 按高度的缓存（`_revoked_cache`）：高度一变（包括刚落地的那条
REVOKE）立即失效，同一高度内复用；返回列表拷贝，调用方改不到缓存。
`tests/test_u15_diagnostics.py` 用带计数的 `load_block` 证明「两次调用只扫一遍」。

## 5. 新脚本：`scripts/smoke_portal.py`

和已有的 `local_smoke.py` 不重复：后者在进程内起 TestClient + 临时链，是改完
代码的自测；新脚本对**已经跑起来的实例**发真实 HTTP，是重启/部署后的体检，
只读（唯一两个 POST 是 mint 持证人链接与「新链接不该能续期」的 403 断言）。

```
python scripts/smoke_portal.py --base http://127.0.0.1:8013 --admin-token demo-staff-token
```

16 项：healthz / version（含 uptime 单位）/ demo credentials / verify / status /
公开报告 PDF（不得含姓名）/ log / whoami / 完整凭证 PDF（必须带 1 个附件）/
custom list 权限 / 持证人链接全链路 / 续期拒绝。没有 admin token 时 staff 部分
标 SKIP，公共模式实例也能跑。

写脚本时自己也踩了两个坑，都记在这里免得下次重复：

- `dict(res.headers)` 保留服务端发的**小写** `content-type`，用 `.get("Content-Type")`
  永远为空 → 两个 PDF 检查假失败。改成大小写不敏感的 `content_type()`。
- 判定值是 `VALID ON CHAIN` 而不是 `VALID`，精确比较会误判。

## 6. 验证

- `tests/test_u15_diagnostics.py` 4 条：uptime 单位、healthz 报 integrity、
  integrity=false → status degraded、撤销扫描只走一遍。
- 全量 `scripts/run_all_tests.py`：**30/30 模块全绿**。
- 对重建后的 8013 跑 `smoke_portal.py`：**16 passed, 0 failed, 0 skipped**。
- `/healthz`：`status=ok height=4 integrity=True`，`bad_blocks` 为空。

## 7. 仍然开着的事

- 坏链备份留在 `data/demo-chain-broken-20261120/`。它不进包，但占据本地空间；
  确认不再需要取证后可以删。
- 旧链里块 12 的签名者（9e:72）已无公钥，这类「签名者被撤销」在协议层没有
  优雅处理：块本身不可验证，整链就只能判 false。真要支持「历史签名者退役」
  需要 `info.yaml` 里保留 retired 签名者的公钥并标记信任区间，那是协议改动，
  不是这一轮的范围。
- `local_smoke.py` 与 `smoke_portal.py` 命名接近，README 里已分别注明用途。
