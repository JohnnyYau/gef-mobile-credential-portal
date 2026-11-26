# U26 — 让别人真的能用：公网可达 + 四步舞台

## 缺口

前两轮把界面做简单了，但 showcase 那天真正的问题是：**服务器在 `127.0.0.1:8013`，
别人的手机打不开。** 二维码扫出来是"拒绝连接"，演示只能是"你看我屏幕"。

而且就算打通了，观众看到的仍是一句话结论；签发、上链、注销这些"过程"全在后台。
"看不到过程"其实是两个问题：**不可达**，和**不可见**。

## 三个拦路石（按遇到的顺序）

1. **本机地址不可达。** 需要一个公网入口。
2. **公网可达后，签发直接 403。** 这是真机才暴露的代码问题：跨站检查
   `_origin_allowed()` 只认 `127.0.0.1 / localhost`，document 里却写着
   "same host allowed"。部署到隧道后，页面自己的 POST 带着公网 Origin 过来，
   被判成跨站 —— 有正确口令也签不出东西。
3. **隧道服务本身不稳。** 免费隧道按 IP 限流、会给页面插广告页、或者干脆连不上。

## 做法

### 1. 公网可达：Cloudflare 快速隧道

```
cloudflared tunnel --url http://127.0.0.1:8013
```

- 无账号，给一个 `https://<随机>.trycloudflare.com`。
- **首次请求返回 429**（`Tunnelstore request failed`）。等一会儿重试即可成功；
  所以启动脚本里写了 6 次重试、每次间隔 30 秒。
- 拿到地址后必须**先改 `PUBLIC_BASE_URL` 再启动门户**，否则 `/api/qr` 和 PDF 里
  印的还是 `127.0.0.1`。
- 同时设 `TRUSTED_PROXIES=127.0.0.1`：cloudflared 从本机回连，对端是
  `127.0.0.1`，这样限流才按**真实访客 IP** 分桶，而不是全场共用一个桶。

试过但不采用的：`localhost.run`（现在要求注册 key，匿名给的连接没有 URL）、
`serveo.net`（22 端口拒绝）、`pinggy` 免费版（可用但会给每个页面套一个
15,463 字节的广告/警示页，观众看不到真页面）、`bore`（Windows Defender 直接
拦下 `.exe`，不绕过安全软件）。

### 2. 同源修复（真机 bug）

`_origin_allowed(origin, host)` 现在拿请求自己的 `Host` 头做同源判断：

```python
if host and parts.hostname:
    request_host = urlsplit("//" + host).hostname or ""
    return parts.hostname.lower() == request_host.lower()
```

只比主机名，不比端口和协议 —— TLS 可能在代理处终止（页面是 https、上游是
http）。这样任何域名/tunnel 部署开箱可用，不再需要把每个部署域名写进
`ALLOWED_ORIGINS`。外来 Origin 仍然 403。

### 3. 过程可见：`/showtime`

一页四个步骤，**全部是真实 API 调用**，不是动画：

| 步骤 | 动作 | 屏幕上出现 |
|---|---|---|
| 01 | `POST /api/custom/build` | 链上第 N 块、验证码、二维码 |
| 02 | `GET /api/verify/{hash}` | ✅ 真的 |
| 03 | `POST /api/revoke` | 已注销，第 M 块 |
| 04 | 再 `GET /api/verify` | ↩ 已注销 ·「签名仍然有效，失效的是机构的承诺」 |

二维码由 `/api/qr` 生成，指向 `PUBLIC_BASE_URL/verify?hash=…`，所以观众
**扫屏幕就能自己验**。深色、1600×900、四步自动走完约 12 秒；`?auto=1` 可无人值守，
`?token=` 只在首次写进 `sessionStorage`，不会显示在界面上。

### 4. 一键启动

`start_showcase.bat`（内部 `start_showcase.ps1`）按唯一正确的顺序做四件事：
清端口 → 开隧道（含 429 重试）→ 用隧道地址作 `PUBLIC_BASE_URL` 启门户 →
等 `/healthz` → 打印地址并打开舞台页。地址同时写进 `showcase-url.txt`。

## 验证

| 项目 | 结果 |
|---|---|
| 公网页面 | `/`、`/issue`、`/showtime`、`/healthz` 全部 200 |
| 公网签发 | `POST /api/custom/build`（带 `Origin: 公网地址`）→ 200，写入第 11 块 |
| 公网版本 | `/api/version` 的 `public_base_url` 与隧道地址一致，链高 13 |
| 舞台四步 | 终态 `↩ 已注销`、链高 13、二维码指向公网地址 |
| 新测试 | `test_hardening` **11 tests**（+4：同源允许、外来 Origin 拒绝、公网页面自发 POST 不被 403、外来页面 POST 被 403） |
| 一键脚本 | 实跑通过，产出 `https://header-ceiling-statements-kingdom.trycloudflare.com` |

## 教训

1. **"部署一下就好"从来不是部署问题。** 真机一跑就撞到跨站检查，单元测试里
    `localhost` 永远通过。公网地址应该进 CI 的冒烟项，而不是靠人肉发现。
2. **QR 的落点由 `PUBLIC_BASE_URL` 决定，不由页面决定。** 忘改这一个环境变量，
   整面墙的二维码全是死链，而页面本身看起来完全正常。
3. **限流键会随部署方式改变。** 加了隧道之后不设 `TRUSTED_PROXIES`，全场共用
   一个桶：一个人连错 5 次，所有人被锁 10 分钟。
4. **免费隧道不是"什么都能凑合"。** pinggy 会插页、bore 被 Defender 拦、
   localhost.run 要注册 —— 能用的只剩 Cloudflare，而它限流。要么接受重试，
   要么上正式部署。
5. **过程要能被看见，才能被相信。** 四个步骤比六张截图有力：观众亲眼看到同一
   张证书从"真的"变成"已注销"。

## 仍开着

- 快速隧道 URL **每次重启都会变**，没有 SLA，笔记本合盖就断；海报上不能印，
  只能投屏或现场贴。
- 观众只能**验证**，不能签发（签发要机构口令，这是有意的）。想让评委自己发，
  得给一张临时口令卡，或者接受"只看不发"。
- 公网实例仍以单进程跑，`data/` 是本地文件；没有对象存储，重启后链还在
  （同一台机器），换机器就没了。
- 没有固定域名/正式部署，因此也没有 HTTPS 证书管理和 uptime 监控。
- `showcase-url.txt` 会被下一次启动覆盖；如需留档请自行复制。
