# U13 — 功能补完计划：把「入口分开了」做成「各角色真的能用」

状态：**F1–F8 全部实施并实测（2026-11-20）；F6 的后端部分在 U14 补齐（见 `U14_auto_improvements.md`）**。U12 解决了「学生看不到签发」，但只解决了「看得见 / 看不见」；这一批解决「拿到手之后能不能用」，以及三处仍然把 hash 当通行证的越权出口。

---

## 0.0 实施结果（先看这里）

| 阶段 | 状态 | 落点 | 实测 |
|---|---|---|---|
| F1 hash 收口 | ✅ | `app/main.py` `_credential_pdf(redact)`；`/api/pdf/{hash}` 报告版、`/api/admin/pdf/{hash}` 全套、`/api/me/{cap}/pdf` 持证人版；`app/pdf_diploma.py` 新增 `redact` 分支（三行身份字段写 `withheld`、**不写 JSON 附件**） | 8013：公开 200 / 3.7KB / `withheld` / 0 附件；admin 无 token 401、有 token 200 / 4.2KB / 1 附件；cap 版 200 / 1 附件；篡改 cap 404 |
| F2 自制/通知收口 | ✅ | 三处装饰器加 `_admin_required` | `/api/custom/list`、`/api/custom/file/...`、`/api/notifications` 无凭证 401，staff 会话/session 下 200 |
| F3 持证人可用 | ✅ | `/api/me/{cap}` 补 `issued_at`、`issued_height`、`revoked_reason`；`_verdict_row` 修掉读错键（`issue_heights` 复数）导致「签发自区块」永远空白的老 bug；holder 页加「下载凭证 PDF」+ 验证二维码 + 签发时间/区块 + 撤销原因 | holder 页实测显示 `签发时间 2026/10/23 17:25:31（区块 #2）`、QR `display:flex`、下载按钮指向 `/api/me/<cap>/pdf` |
| F4 角色界面 | ✅ | 新端点 `GET /api/staff/whoami`（role / demo_open / session_seconds_left）；console 按 role 隐藏 tab 与 `data-role` 卡片，徽章显示「角色 ADMIN · 会话剩 30 分钟」 | ADMIN：9 tab 全开；ISSUER：只剩 home/verify/student/chat/log/issue，单个签发与 API keys、通知卡隐藏，`goCustom` 卡隐藏 |
| F5 批量链接 | ✅ | `/api/issue/batch` 每行返回 `holder_path`、`credential_pdf_url`、`student_id`；`/api/issue` 同样返回 | 批量 1 行 → `holder_path` `/me/<cap>`，取该链接 `/api/me/<cap>` 200 且 hash 一致；结果表新增「持证人链接」按钮与「导出全部持证人链接 CSV」 |
| F6 会话治理 | ✅ 完成 | U13：`authz.staff_session_remaining()` + whoami 返回剩余秒，界面倒计时并在归零时回登录页。U14：`STAFF_SESSIONS_PER_ROLE=3` + 按角色淘汰、`drop_staff_sessions`、`POST /staff/logout/all`、登录失败限流（5 次 / 10 分钟 / 429 + `Retry-After`）、staff 页「退出所有设备」 | 会话剩余时间逐秒递减；U14 实测 dropped=2 且 issuer 会话不受影响，限流在令牌读取前生效 |
| F7 fail-closed | ✅（默认值取了保守方案） | `config.DEMO_OPEN`（默认 `1`，保持演示兼容）；`authz.check_roles` 在未配 token 且 `DEMO_OPEN=0` 时 401 并给出原因；`/api/version` 暴露 `demo_open`；公开页 `publicNote` 显式提示 | 无 token + `DEMO_OPEN=1`：`demo_open:true`、`/api/custom/list` 200；`DEMO_OPEN=0`：401 + `No role token is configured ... DEMO_OPEN=0` |
| F8 回归 | ✅ | 新增 `tests/test_u13_hardening.py`（9 条：报告版/姓名不出现/端点矩阵/持证人 PDF 与篡改/自制与通知 401/签发点与撤销原因/whoami/批量链接/DEMO_OPEN 开关） | 全量 **28/28 模块绿**，前端 harness 34/34 |

与原计划的差异，三处：**报告版 PDF 不附 JSON 附件**（附了就等于把明文一起送出去，这是实施时才想清楚的关键点）；**`DEMO_OPEN` 默认仍为 1** 而不是计划里的 0（默认改 0 会让 27 个测试模块与演示启动全部失效，代价与收益不成比例，改为「显式开关 + 界面明说」）；**F7 返回 401 而不是 503**（这是身份问题，不是服务不可用）。

---


## 0. 一句话结论

U12 之后，角色在**页面上**分开了，在**数据出口上**还没有。现在这三条路不需要任何身份就能走通：

| # | 现状 | 位置 | 后果 |
|---|---|---|---|
| A | `GET /api/pdf/{hash}` 匿名返回完整凭证 PDF | `app/main.py:1157` | 任何人拿到一个 hash（公开日志、QR、分享链接里都有）就能下到含姓名、学号、DOB 的 PDF。hash 事实上成了 bearer token |
| B | `GET /api/custom/list`、`GET /api/custom/file/{id}/{kind}` 匿名 | `app/main.py:613`、`app/main.py:623` | 任何人可枚举并下载全部「自制凭证」的 PDF / JSON，同样是明文 PII |
| C | `GET /api/notifications` 匿名 | `app/main.py:1276` | 内部投递记录（收件地址、凭证哈希、状态）对公众可见 |

U12 把「签发入口」藏到了 `/staff`，但 A/B/C 让它可以从后门把同样的东西取走。功能上这叫**入口分离、出口未分离**。

第二类问题不是漏洞，是「不合用」：

- 持证人打开 `/me/<link>` 只能看到状态，**不能下载自己的 PDF、QR，也看不到撤销原因**（`static/holder.html` 只有一个「公开验证」链接）。
- 批量签发 20 份之后，**没有地方一次导出 20 条持证人链接**，只能逐个点「取链接」。
- `ISSUER_TOKEN` 与 `ADMIN_TOKEN` 在**后端**是分开的，在**界面上**没有区别：只配签发 token 的人登录后照样看到「注销」「签发方」「API 密钥」tab，点下去才 403。
- 通知队列在内存里，**进程重启即丢**；`status` 只活在返回值里，事后无从对账。
- `authz.check_roles` 在「一个 token 都没配」时**直接放行**（`app/authz.py:112-114`）。演示方便，但部署时忘配一个变量就等于全开。

---

## 1. 功能盘点（已核对代码，不是推测）

| 端点 | 鉴权现状 | 返回内容 | 判定 |
|---|---|---|---|
| `GET /` | 公开 | 公开页 | 正确 |
| `GET /me/{cap}`、`GET /api/me/{cap}` | 签名链接 | 单份凭证（遮 PII） | 正确，但信息不够（无 PDF/QR/撤销原因） |
| `GET /api/holder-link` | staff | 一条链接 | 正确，但只能一条一条来 |
| `GET /api/pdf/{hash}` | **无** | 完整 PDF（含 DOB） | **必须收口** |
| `GET /api/custom/list`、`/api/custom/file/...` | **无** | 自制凭证 PDF/JSON | **必须收口** |
| `GET /api/notifications` | **无** | 投递记录 | 收口到 staff |
| `GET /api/verify/{hash}`、`/api/status/{hash}` | 公开 | 判定 + 遮罩信息 | 正确 |
| `POST /api/verify/document`、`/api/verify/batch` | 公开 | 判定 | 正确 |
| `GET /api/disclose` 系列 | 公开 | 可隐藏身份段 | 可接受，但不应成为拿明文的旁路 |
| `POST /api/issue`、`/api/issue/batch` | ADMIN 或 ISSUER | 签发 | 正确 |
| `POST /api/revoke` | ADMIN | 撤销 | 正确（界面未体现） |
| `/api/signers*`、`/api/admin/apikeys*`、`/api/admin/audit` | ADMIN | 管理 | 正确（界面未体现） |
| `GET /api/admin/chain-snapshot` | ADMIN | 快照 | 正确 |
| `POST /staff/login` | token → 会话 | cookie | 正确，缺失败计数与并发上限 |

---

## 2. 阶段计划

每阶段都可以独立上线、独立回滚；F1–F3 是「不改架构就能做完」的最小集。

### F1 · 收口 hash-as-bearer（最高优先）

**做法**

1. `GET /api/pdf/{hash}` 拆成三档：
   - `GET /api/me/{cap}/pdf` —— 持证人本人，凭 capability 下载自己那份；
   - `GET /api/admin/pdf/{hash}` —— staff 会话下载（补发、存档用）；
   - `GET /api/pdf/{hash}` 保留但只返回**验证报告**（判定 + 六项检查 + 链高，无姓名/DOB），文件名 `verification-{hash12}.pdf`。
2. 公开页「下载 PDF 凭证」按钮改为「下载验证报告」，指向报告档；持证人页新增「下载我的凭证 PDF」。
3. `pdf_diploma.render_diploma_pdf` 增加 `redact=True` 分支（复用同一模板，个人段替换为「已隐藏」）。

**验收**

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/pdf/<hash>          # 200，但为报告版（无 DOB）
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/admin/pdf/<hash>    # 401（无会话）
curl -s -o /dev/null -w '%{http_code}\n' "localhost:8000/api/me/<cap>/pdf"      # 200，application/pdf
curl -s "localhost:8000/api/me/<cap>?tamper=1"                                   # 404
```

**风险**：PDF 是「可离线验证」的载体，报告版不含内嵌 JSON，不能替代凭证本体 —— 这正是要的效果：凭证本体只能由持证人给雇主。

---

### F2 · 自制凭证与通知收口

**做法**

1. `/api/custom/list`、`/api/custom/file/{id}/{kind}` 加 `dependencies=[Depends(_admin_required)]`（staff 会话已可用，前端本来就在 staff 页）。
2. `/api/notifications` 同上；公开日志页删掉「通知记录」卡片，staff 页补一张。
3. `custom_service.resolve_file` 保持路径安全校验，不改签名。

**验收**

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/custom/list        # 401
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/notifications      # 401
# staff 会话（cookie）下均 200
```

---

### F3 · 持证人功能补全

**做法**

1. `/api/me/{cap}` 返回值补：`pdf_path`、`qr_path`、`verify_path`、`expires_at`、`revoked`（bool）、`revoked_reason`、`revoke_effective_date`。撤销信息从链上 REVOKE 区块读，与验证判定同源。
2. `holder.html`：加「下载 PDF / 下载 QR / 复制给雇主」三个按钮；撤销时顶部显示原因与生效日期；底部显示「这条链接 YYYY-MM-DD 到期」。
3. QR 直接复用 `/api/qr/{hash}`（公开，只含 hash，不含 PII），无需新端点。

**验收**

```bash
curl -s "localhost:8000/api/me/<cap>" | grep -E 'pdf_path|expires_at|revoked'
curl -s -o /tmp/q.png -w '%{http_code}\n' "localhost:8000/api/me/<cap>/pdf"
# 撤销该凭证后重开 /me/<cap>：status=REVOKED 且带 reason
```

---

### F4 · 角色真正落地（最小权限）

**做法**

1. 新增 `GET /api/staff/session`（只读）：返回 `{role, expires_in}`，读会话 cookie。
2. `staff.html` 的 tab 加 `data-roles="admin issuer"`；`main.js` 启动时取一次 role，隐藏不在集合内的 tab（VERIFIER 只剩「核验 / 日志」）。
3. 后端按最小角色收紧：
   - `issue`、`issue/batch`、`custom/build` → `ISSUER|ADMIN`
   - `revoke`、`signers*`、`admin/apikeys*`、`admin/chain-snapshot` → `ADMIN`
   - `admin/audit` → `ADMIN|ISSUER`
4. 会话里存 role，`read_staff_session` 返回 `(role, expires)`，`check_roles` 用它做集合判断（现在就做了，只是没暴露给前端）。

**验收**

```bash
# 只配 ISSUER_TOKEN
curl -s -o /dev/null -w '%{http_code}\n' -H "X-Admin-Token: $ISSUER" -X POST localhost:8000/api/issue -d @doc.json   # 200
curl -s -o /dev/null -w '%{http_code}\n' -H "X-Admin-Token: $ISSUER" -X POST localhost:8000/api/revoke -d '{}'      # 403
```

---

### F5 · 批量签发 → 链接一次性导出

**做法**

1. `POST /api/issue/batch` 响应每条加 `holder_link`（`capability.mint`，TTL 取请求的 `link_ttl_days`，默认 30）。
2. 新增 `GET /api/holder-links.csv?hashes=a,b,c&ttl=30`（staff）：返回 `sid,hash,credential_type,link,expires_at`。
3. staff 批量结果表加「下载链接 CSV」；单条结果旁加「复制链接」。

**验收**

```bash
curl -s -X POST -H "X-Admin-Token: $ADMIN" localhost:8000/api/issue/batch -d @batch.json | jq '.issued[0].holder_link'
curl -s -H "X-Admin-Token: $ADMIN" "localhost:8000/api/holder-links.csv?hashes=..." | wc -l   # = 条数 + 1
```

---

### F6 · 会话治理与审计

**做法**

1. `POST /staff/logout/all`：按 role 清空全部会话；staff 页「退出所有设备」。
2. 每角色并发会话上限 3，超出淘汰最旧（`InMemorySessionStore` 已有 limit，按 role 分桶即可）。
3. 登录失败计数：同 IP + role 10 分钟 5 次 → 429，成功即清零。
4. 审计 actor 写 `staff:<role>`，`/api/admin/audit` 可按 actor 过滤。

**验收**

```bash
for i in 1..5; do curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/staff/login -d '{"token":"wrong"}'; done
# 前 4 次 401，第 5 次 429
curl -s -X POST -b "staff_sid=$S" localhost:8000/staff/logout/all   # 200，随后旧 cookie 访问 /staff → 303
```

**实际落地（部分）**：只做了 `authz.staff_session_remaining()` + whoami 的 `session_seconds_left`，console 显示「会话剩 N 分钟」并在归零时回登录页——注册员不会在批量签发途中被静默踢出。`logout-all`、按角色并发上限、登录失败限流**未做**：单实例演示、会话本就是内存态（重启即清空），这三项的改动面大于收益。

---

### F7 · 默认拒绝（fail-closed）

**做法**

1. `config.py` 加 `DEMO_OPEN`（默认 `0`）。`authz.check_roles`：未配置该角色 token 且 `DEMO_OPEN=0` → `503 "no staff token configured"`；`DEMO_OPEN=1` 才保留现在的放行。
2. `start_portal.bat`、`start_portal.sh`、`render.yaml` 显式写 `DEMO_OPEN=1`（演示实例）或 `ADMIN_TOKEN=...`（私有实例）。
3. 测试夹具 `conftest.py` 设 `DEMO_OPEN=1`，310 条断言不变。

**验收**

```bash
env -u ADMIN_TOKEN -u ISSUER_TOKEN uvicorn app.main:app &   # 不设 DEMO_OPEN
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/api/issue -d @doc.json   # 503
DEMO_OPEN=1 uvicorn app.main:app &
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/api/issue -d @doc.json   # 200（演示行为）
```

**实际落地（与上面的差异）**：`DEMO_OPEN` 默认 `1`（保持 27 个测试模块与 `start_portal.bat` 的演示行为不变），设为 `0` 才 fail closed，且返回 **401**（身份缺失）而不是 503；`/api/version` 与公开页都会把 `demo_open` 明说出来，避免「静默全开」。

---

### F8 · 回归矩阵

新增 `tests/test_u13_authz.py`，约 20 条：

| 组 | 断言 |
|---|---|
| 匿名矩阵 | `/api/pdf`（报告版 200）、`/api/admin/pdf` 401、`/api/custom/*` 401、`/api/notifications` 401 |
| capability | 有效 cap 下 PDF 200、篡改 404、过期 404、跨凭证不可用 |
| 角色 | ISSUER 可签发不可撤销；ADMIN 全开；VERIFIER 只读 |
| 会话 | logout-all 后旧 cookie 失效；第 4 个会话淘汰最旧；5 次错 token → 429 |
| fail-closed | 无 token + DEMO_OPEN=0 → 503；DEMO_OPEN=1 → 200 |
| 回归 | 全量 27 模块仍绿 |

冒烟脚本 `slides_work_v2/check_u13.py`（8 条，对真实服务）：匿名三处 401、报告版 PDF 200、持证人 PDF 200、ISSUER/ADMIN 分权、logout-all、fail-closed 503。

**实际落地**：`tests/test_u13_hardening.py`（9 条，integration 档，已登记进 `scripts/run_all_tests.py` 与 `tests/tiers.py`），全量 **28/28**；冒烟没用独立脚本，改为对 8013 真实服务的 curl 矩阵 + `bu` 浏览器读页面状态（结果见 §0.0）。

---

## 3. 排期

| 版本 | 内容 | 预估 |
|---|---|---|
| **最小集（先做）** | F1 + F2 + F3 | 半天 |
| 可用集 | + F5（链接导出）+ F4（角色界面） | 再半天 |
| 收口集 | + F6 + F7 + F8 | 再一天 |

F1/F2 是纯后端装饰器 + 一处 PDF 分支，改动面最小、收益最大，建议**先单独做完、单独验证**，再动 F3 之后的 UI。

## 4. 回滚

| 阶段 | 回滚方式 |
|---|---|
| F1 | 恢复 `diploma_pdf` 单一路由；报告版函数保留但未接线 |
| F2 | 去掉三处 `dependencies` |
| F3 | `/api/me/{cap}` 多出的字段对旧前端无害，可保留；holder 页改动用 git 还原 |
| F4 | `data-roles` 忽略即可（前端不读就不隐） |
| F5 | 批量响应多出字段对旧前端无害 |
| F6/F7 | 配置开关回退（`DEMO_OPEN=1`） |

## 5. 明确不做

- 不做 OIDC / SSO / 多租户：当前是单校演示实例，角色就三个。
- 不做真实邮件发送：`NOTIFY_TO` + dry-run 已够，接 SMTP 属于部署环境问题。
- 不做移动端原生 App：现有页面已响应式。
- 不把 capability 换成 JWT：HMAC + 单凭证 payload 更小、更易审计，没有换的理由。
- 不做「持证人一次看全部凭证」：这与 U12 的隐私取舍相反；批量链接导出（F5）已经覆盖「我要把自己的凭证都收好」的真实需求。

---

## 6. 与 U12 的关系

U12 关闭的是**入口**（谁能看到签发、注销、签发方）。U13 关闭的是**出口**（谁能把明文取走）与**接口可用性**（持证人能不能真的用上那条链接）。两批合并后，完整的一句话是：

> 公开的人只能验证；持证人只能取自己那一份；教职员按角色只能做自己那一档；三者的证据都来自同一条链。
