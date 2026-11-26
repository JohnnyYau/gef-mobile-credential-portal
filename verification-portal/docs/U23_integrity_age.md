# U23 — 缓存必须承认自己有多旧

U15 给链完整性加了 30 秒缓存：`/healthz` 与 `/api/version` 每次请求都跑全链验签太贵，所以按「链目录 + 高度」缓存。缓存本身是对的，问题在于**结果长得和实时结论一模一样**：

```json
"integrity": { "ok": true, "bad_blocks": [] }
```

块刚坏掉、签名者刚退役、高度刚变化的那几十秒里，这个 `true` 是过去的 `true`，而任何读者都看不出来。系统不是说了假话，是**省略了它是在什么时候说的**。

---

## 加两个字段，别改语义

```python
def _integrity_view(ok, bad, checked_at):
    return {"ok": bool(ok), "bad_blocks": list(bad),
            "checked_at": round(checked_at, 1),
            "age_s": round(max(0.0, time.time() - checked_at), 1)}
```

- `checked_at` —— 这次结论实际算出来的时刻（epoch 秒）。缓存命中时保留**原来**的时间戳，不刷新。
- `age_s` —— 距今多少秒。

关键在「缓存命中不刷新 `checked_at`」：如果每次读取都把它更新成当前时间，这两个字段就退化成"永远 0 岁"，等于没加。测试里有专门一条：

```python
first = main.chain_integrity()
second = main.chain_integrity()
self.assertEqual(first["checked_at"], second["checked_at"],
                 "a cached verdict must not pretend to be a new scan")
```

读取方没有变化：PDF 渲染读 `integrity.get("ok")`，U19 的测试断言 `ok` 与 `bad_blocks`，都还在。新字段是纯附加。

`_integrity_view` 同时照顾错误分支（链目录读不出来）：那种情况下「扫描失败」是此刻发生的，所以 `checked_at = now`、`age_s = 0`，并在外面附 `error` 字段。

## 运维脚本要覆盖新端点，否则等于没做

U19 加了 `/api/diagnostics`，但 `scripts/smoke_portal.py` 一直没查它——部署后没有任何自动检查证明这个端点在本实例上是通的。U23 补上，同时补上 U19 那个 QR 事故的运维级护栏：

| 新增检查 | 为什么 |
|---|---|
| `GET /api/diagnostics` 无凭证 → 401/403 | 配置正文不能匿名读；`DEMO_OPEN=1` 时按实例情况 SKIP |
| `GET /api/diagnostics` 带凭证 → 200，`warnings` 是 list | 证明「正文」真的返回，而不是又一次只给计数 |
| `diagnostics` 的 `chain.integrity.age_s` 是数字 | 证明缓存年龄可见 |
| `/healthz` 的 `integrity` 含 `checked_at`/`age_s` | 公开面也有年龄 |
| `/api/pdf/{hash}` 第 1 页内嵌图 ≥ 1 | **QR 真的在**——六轮静默失败就是没人查这个 |

最后一条是重点。U19 修好了 QR，但当时只在单测里断言；一个部署上线后 QR 会不会再次消失，运维脚本本来无从得知。现在 `smoke_portal.py` 会打印 `1 image(s)`，没有图就 FAIL。

## 验证

| 项 | 结果 |
|---|---|
| U23 模块 | 8/8 |
| 全量第一次 | **37/38**——`tests.test_chain_cache` 失败，见下节 |
| 全量第二次 | **37/38**——换成 `tests.test_restart_persistence` 失败（同一类问题：时间常数与环境争用） |
| 两个模块修完后 | `test_chain_cache` 连跑 3/3、`test_restart_persistence` 3 tests OK |
| `smoke_portal.py` | **20/20**（原 16 + 4 新项；本实例 `demo_open` 为 false，401 真跑到了） |
| 实测年龄 | `/healthz` `age_s=0.0`（刚重算）、`/api/diagnostics` `age_s=1.1`（同一份缓存） |

单测覆盖：字段存在且类型正确、缓存命中不改时间戳、过 TTL 会重算（用人为旧 `ts` 构造，断言新时间戳比旧值新 40 秒以上）、可 JSON 序列化、两个端点都带年龄、公开端点仍只有计数（U19 的拆分不被 `checked_at` 破坏）、坏链缓存也带时间。

## 补充：全量不是 38/38，问题在缓存和测试两边

第一次跑全量就掉了一个模块：`test_chain_cache` 的 `same fingerprint + live TTL: cached replay` 断言失败。那条测试把 `CHAIN_INTEGRITY_TTL` 设成 **0.05 秒**，先预热缓存、再把一个块原地改写（保持字节数与 mtime，所以指纹不变），然后断言「TTL 内应读到缓存」。

实测这个 5 块链的冷扫描要 **0.03–0.24 秒**——第一次通过纯属运气。TTL 和一次扫描同一个量级时，测试量的不是缓存，是这台机器今天有多快；后台多跑一个 uvicorn、磁盘冷缓存没热，它就翻脸。

顺带暴露出产品侧一个真问题：`verify_chain()` 写入缓存用的是**扫描开始前**的时间戳（这是对的，它诚实地表示结论有多旧），但写入条件只看 `ttl > 0`。于是当「扫一次比 TTL 还慢」时，会写入一条**出生即过期**的条目：它永远读不到，只会占位，下一次扫描再把它替换掉。缓存看起来在工作，其实一次没命中。`_status_index()` 是同一写法。

修法两处：

```python
if ttl > 0 and time.time() - now < ttl:   # 写入前再判一次：扫完已经过期就别存
    with _CACHE_LOCK:
        _CHAIN_CACHE[chain_addr] = (fingerprint, now, ok, report)
```

测试改为 TTL 0.5 s / 睡 0.7 s（0.5 秒明显大于一次冷扫描，才是真在测 TTL），并新增一条：TTL 为 0 与 0.0001 时都不得在 `_CHAIN_CACHE` 里留下条目。连跑三次 3/3。

第二次全量又换了一个失败者：`test_restart_persistence`（75 秒后 `False is not true`，单跑 14 秒通过）。它起真的 uvicorn 子进程等 `/healthz`，`_wait_ready` 只会说「还没好」，而且子进程的 stdout/stderr 全丢进 `DEVNULL`——服务器根本没起来时，你看不到任何原因，只能白等 30 秒再猜。这是测试自身的可诊断性缺口，改了两点：

1. `_wait_ready(base, timeout, proc)`：进程已退出就立刻返回 False，不再把超时耗满；
2. uvicorn 的输出写进 `%TEMP%\portal-restart-test.log`，断言失败时附上最后 8 行（`--- uvicorn said:`）。

新增 `test_dead_server_does_not_burn_the_timeout`（用一个立刻退出的子进程，断言 2 秒内返回），把「早退即失败」本身也锁住。旧的 4 处 `assertTrue(_wait_ready(...))` 全部改走 `_assert_ready()`。


## 教训

1. **缓存与说谎之间只差一个时间戳。** 同样的响应体，知道年龄就是"可能有 30 秒延迟"，不知道年龄就是"现在是好的"。
2. **新端点需要运维级检查，测试通过不等于部署可用。** 单测跑的是进程内实例，`DEMO_OPEN`、代理头、静态挂载都不在其中。
3. **给缓存加字段时，不要「顺手」更新它。** 把 `checked_at` 刷成当前时间会让整个改动失效，而测试如果不专门断言"两次调用相等"，根本发现不了。
4. **测试里的时间常数要和被测系统的量级对齐。** 0.05 秒不是「一个很短的 TTL」，它等于「一次扫描的时间」；用它写断言，等于在断言这台机器此刻有多快。这类测试今天绿、明天红，而且红的时候看不出是环境还是代码。
5. **测试失败了却拿不到被测进程的话，等于没写。** `DEVNULL` 省下的两行代码，换来的是每次失败都要手工重跑一遍才知道为什么。日志留档 + 进程早退即失败，是超时等待的两条底线。

## 剩下的真实边界

1. **多 worker 各自缓存。** 进程内 `_integrity_cache` 不跨进程；两个 worker 会各自算、各自报年龄，同一秒的两个请求可能看到 `age_s=0.0` 和 `age_s=12.4`。`/healthz` 的 `observability.counters_shared_across_workers: false` 已经在提示这件事，但没有把 integrity 缓存也算进去。
2. **`checked_at` 是服务端时钟。** 时钟不准时，年龄也不准；跨时区阅读时要记得它是 epoch 秒而不是本地时间字符串。
3. **`age_s` 精度是 0.1 秒。** 对 30 秒的 TTL 足够；如果将来 TTL 缩到秒级，这个精度会显得粗糙。
4. **年龄本身不触发动作。** 现在没有任何逻辑说"年龄超过 N 就强制重算"——TTL 已经保证了上限。但如果将来把 TTL 调大（例如为了省 CPU 调到 5 分钟），`age_s` 只是披露，不会保护任何人；那需要另一个决定。
5. **PDF 里没有印检查时间。** 一张纸上的 `CHAIN INTEGRITY FAILED` 是「此文件生成时链是坏的」，但读者无法知道那一刻有多久以前。要在 PDF 上打时间戳，就得决定用哪种时区格式，本轮没做。
