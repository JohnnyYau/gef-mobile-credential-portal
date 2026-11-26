# U24 — 谁才是"客户端"：X-Forwarded-For 的信任边界

## 缺口

U16 把限流和登录失败窗口统一到 `_client_ip()`，解决了"一个反向代理让所有人共用一个桶"的问题。但那个函数**无条件**读 `X-Forwarded-For` 的第一段：

```python
forwarded = request.headers.get("x-forwarded-for", "")
return (forwarded.split(",")[0].strip()
        or (request.client.host if request.client else "unknown"))
```

于是对于一个**前面没有代理**的实例，任何一个匿名调用者只要每次换一个伪造地址，就得到一个全新的桶：

- 120 次/分的公开限流器对它没有意义；
- `LOGIN_FAIL_MAX=5 / 600s` 的登录锁对它没有意义；
- 审计日志里记下的也是伪造地址。

反过来也可以故意填一个固定地址，把**别人**的桶打满。

这不是理论风险。先按旧代码实测一次：带 9 个不同的伪造 `X-Forwarded-For` 打 `/staff/login` 错误口令，9 次全部返回 401——一次都没被锁。

## 第一层：应用侧不再无条件相信

新增 `TRUSTED_PROXIES`（逗号分隔 IP / CIDR），默认空。

```python
peer = request.client.host if request.client else "unknown"
nets = _proxy_nets()[0]
if not _is_trusted_proxy(peer, nets):
    return peer                       # 没代理（或对端不是代理）：完全不看 XFF
hops = [...XFF 各段（去除空白）...]
for hop in reversed(hops):
    if not _is_trusted_proxy(hop, nets):
        return hop                    # 从最右往左，第一个不可信的跳才是客户端
return hops[0]                        # 全是可信代理：最左就是客户端
```

要点：

- **从右往左找**。客户端可以在 XFF 左边写任何东西，只有"离我们最近、且不属于可信代理"的那一跳是可信事实。
- **对端必须是可信代理**才读 XFF。对端自己说"我是代理"不算。
- 解析失败的地址（`testclient`、`unknown`、带端口的字符串）一律视为不可信——所以桶键可能是个怪字符串，但绝不会被误当成可信。
- `TRUSTED_PROXIES` 里的非法项不吞掉：`startup.py` 会点名报一条 warning。这个配置写错的后果是"所有人回到一个桶"，只能靠日志发现。

披露：

- `/healthz` 的 `checks.observability.client_ip_source` = `"peer"` 或 `"x-forwarded-for"`（公开，不带具体网段）。
- `/api/diagnostics` 的 `client_ip` = `{source, trusted_proxies, invalid_entries}`（staff-only，因为会点出内网网段）。
- `/api/staff/whoami` 新增 `client_ip`：**这一个请求实际被计入哪个桶**。

## 第二层：真正的绕过点在 uvicorn，不在应用

应用改完后实测：**9 次伪造请求依然全部 401**。

原因：`uvicorn` 默认 `--proxy-headers` 开启，且默认 `--forwarded-allow-ips=127.0.0.1`。它在**应用之前**就把 `X-Forwarded-For` 写进 ASGI 的 `scope["client"]`。也就是说：

- 实例跑在本机 `127.0.0.1` 时，peer 被认为是可信代理；
- 应用拿到的 `request.client.host` 已经是伪造值；
- 应用的 `TRUSTED_PROXIES` 判断只看到一个"来自 203.0.113.x 的请求"，于是按 peer 记账——记的是伪造的那个。

这和 U16 修的是同一类病：**同一条事实被两层各自决定一次，谁在后面谁说了不算**。

修法：

1. **启动命令一律加 `--no-proxy-headers`**：`start_portal_verify.bat`、`start_portal_admin.bat`、`start_portal.sh`、`Dockerfile`、`railway.toml`、README（根与 portal）、USAGE 三处示例、DEPLOY 的 Render 段。
2. **真的在代理后面**时：`--forwarded-allow-ips=<代理地址>` **并且** `TRUSTED_PROXIES=<同一地址>`，两层指向同一个事实。只配一层是最容易犯的错。
3. **运维探测**（`smoke_portal.py`）：带 `X-Forwarded-For: 203.0.113.5` 请求 `/api/staff/whoami`，读回 `client_ip`。若它变成了 `203.0.113.5`，说明有某层在重写 peer，FAIL 并直接提示「start it with --no-proxy-headers」。

## 验证

| 项 | 结果 |
|---|---|
| `tests.test_u24_proxy_trust` | **17/17** |
| 全量第一次 | **38/39**——`tests.test_hardening` 失败，见下节 |
| 全量第二次（修完） | **39/39** |
| 实机（旧代码 + 本机 8013） | 9 次伪造 XFF → **9 × 401**（一次都没锁） |
| 实机（修复后，`--no-proxy-headers` + 8013） | 第 **6** 次 → **429**（锁住） |
| `whoami` 带伪造头 | `client_ip=127.0.0.1`（伪造值未被采信） |
| `smoke_portal.py` | **22/22**（原 20 + `client_ip_source` + 伪造 XFF 探测） |

单测覆盖：默认忽略 XFF、每次换伪造地址仍是同一个桶、非 IP 对端、可信对端采信、CIDR、多跳取最右不可信跳、全可信时取最左、不可信对端不能自称代理、空/空白头回落到对端、scope 里没有 client 时为 `unknown`、非法配置项被点名且信任集合为空、`healthz` 两种 `client_ip_source`、`diagnostics` 列出网段与非法项、公开面不泄露网段、以及端到端「5 次失败 + 第 6 次换头仍 429」。

## 连带影响：一个靠 XFF 造桶的旧测试

`test_hardening.test_rate_limit_429` 原本用 `headers={"X-Forwarded-For": "9.9.9.9"}` 给自己造一个"独立桶"，再把 `RATE_LIMIT_PUBLIC_MAX` 压到 3 跑满。XFF 不再被采信后，那个桶不存在了：该请求落到与同模块其他请求共享的 peer 桶（`testclient`），3 次额度早被用光，于是第一次就 429。

改成：

```python
RATE_PEER = ("9.9.9.9", 5000)
cls.rate_client = TestClient(main.app, client=RATE_PEER)
```

用**独立的 TCP 对端**造桶。这比伪造头更接近事实——真实世界里区分客户端本来就靠对端地址，而不是靠调用者自己声明的头。也让「哪个才是客户端」这件事在测试里只有一种说法。

## 教训

1. **"统一到一处"不等于"在那里判断对了"。** U16 把两个键收拢到一个函数，但那个函数本身是错的；收拢只是让错误更一致。
2. **信任边界要问"谁写的这个头"，而不是"头里写了什么"。** 决定 XFF 可信度的是 TCP 对端，不是 XFF 的内容，更不是调用者的自我声明。
3. **同一个事实只能有一层拍板。** uvicorn 和 FastAPI 都能决定"客户端是谁"；默认配置下 uvicorn 先手，应用层写得再对也无效。部署命令因此是安全边界的一部分，不是运维细节。
4. **能实测就别只写测试。** 单测 17 条全绿，实机 9 次全 401——差的那一层根本不在 Python 里。
5. **旧测试的"作弊手段"会随信任模型一起失效。** 伪造头曾经既是攻击面，也是测试里造隔离的便利工具；改掉信任模型时，必须再审一遍有多少测试靠这个便利在跑。

## 仍开着的边界

1. **`TRUSTED_PROXIES` 只管 TCP 对端，不管代理本身是否被攻破。** 代理若把客户端自带的 XFF 原样拼到链上（而不是追加），最右一跳会变成伪造值。
2. **只认 IPv4/IPv6 字面量。** 代理放在 Unix socket 上时（uvicorn 支持 `--uds`），对端不是 IP，XFF 一律不采信——这时只能用代理侧改写 `scope`，属于部署层。
3. **`TRUSTED_PROXIES` 变更需要重启。** 它是启动时读的环境变量，`_proxy_nets()` 只缓存"同一个字符串的解析结果"，不做文件监视。
4. **限流桶仍是进程内。** 多 worker 下每个进程各有一份计数（与 U23 的缓存年龄问题同源），`/api/metrics` 与 `/healthz` 已披露 `counters_shared_across_workers=false`。
5. **`client_ip` 只回显桶键，不回显原始 peer。** 当两层不一致时（例如 uvicorn 重写了 peer），单看这个字段无法区分；这也是 smoke 用"伪造值有没有出现"来判断、而不是比较两个字段的原因。
