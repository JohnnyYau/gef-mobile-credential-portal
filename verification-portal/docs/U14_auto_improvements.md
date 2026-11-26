# U14 — 自主改进轮（会话治理 / 撤销标注 / 链接续期）

U13 之后的状态：入口分开了（谁能看到签发、注销、签发方），出口也分开了
（明文凭证只给持证人和员工）。这一轮不再由清单驱动，而是先盘点代码找
「用起来会出事」的地方，再自己决定改什么、自己验证。

## 0. 盘点：先否掉两件「看起来该做」的事

| 候选 | 结论 | 依据 |
|---|---|---|
| 通知记录重启即丢 | **否掉** | `notifier` 已经通过 `repository.store("notifications")` 落盘到 `<chain-dir>/../notifications.jsonl`；lifespan 关闭时也会 `drain(flush=True)`。只有队列里尚未处理的条目会丢，量级是一两条 |
| 给公开验证报告加 QR | **否掉** | `pdf_diploma.py` 两个版本都已经画 QR（28 mm，`Scan to verify`），报告版从不缺这一块 |

否定这两个候选，是为了不把「已经做过的功能」当成新功能再讲一遍。

## 1. 会话治理收口（U13 F6 的后半段）

U13 F6 只做了前端的会话倒计时和到期回登录页。服务端的会话仍然是「只要不
退出就一直有效」，有三个具体后果：忘关的标签页可以永久占住一个角色；换设备
登录后旧设备还在；登录表单可以无限次试 token。

落地：

- `session_store.InMemorySessionStore.items()` — 按 LRU 顺序返回 `(sid, value)`
  拷贝。按角色计数和淘汰需要遍历，而原来的 `get/set/delete` 都不暴露顺序。
- `authz.STAFF_SESSIONS_PER_ROLE = 3` — `create_staff_session(role)` 建完就调
  `_evict_oldest_for_role(role)`，超出三条从列表头部删。`read_staff_session` 的
  `get` 会 `move_to_end`，所以「最旧」实际是「最久没用」，符合直觉。
- `authz.drop_staff_sessions(role=None)` — 按角色清空。`POST /staff/logout/all`
  先 `read_staff_session` 拿调用者角色，再只清这个角色：签发方不能顺手把管理
  员踢下线。
- `authz.LOGIN_FAIL_WINDOW = 600` / `LOGIN_FAIL_MAX = 5` — 每个来源地址一个
  时间窗，`/staff/login` 在读 token **之前** 先查 `login_allowed`，超限直接 429
  并带 `Retry-After`。失败记一笔，成功清零。
- 前端：`staff.html` 在「退出」旁加「退出所有设备」，`main.js` 的委托同时匹配
  两个按钮，`all` 时打 `/staff/logout/all`。

## 2. 撤销后的 PDF 自我标注

链上撤销是实时生效的（`/api/verify` 下一次就返回 REVOKED），但已经发出去的
PDF 是静态文件：撤销之后它仍然印着「REAL / VALID」，看起来和真凭证一样。这
不是链的漏洞，是文件的属性，只能把事实画到文件上。

- `render_diploma_pdf(..., revocation=None)` — 新 kwarg，带默认值，所以调用点
  不用改签名。
- 页脚上方 26–38 mm 的空白带画红框：`REVOKED ON CHAIN — block #N`，第二行
  `Reason: …` 或 `No reason was recorded by the issuing side.` 该区域在 rows
  （约 168 mm 结束）、hash 框（约 145 mm）、QR（约 100 mm）与页脚（18/14.5 mm）
  之间，不会压到任何已有元素。
- `_credential_pdf` 渲染前取 `chain_service.revoke_meta(hash)`；链损坏时按「无
  撤销」处理，不能让 PDF 因为链读不出来而 500。
- 公开报告版同样带这条红框——**「已撤销」本身不是隐私**，隐瞒反而有害。

## 3. 持证人链接续期

30 天 TTL 的链接到期后，持证人只能去找签发方。实际上持有人自己就能证明自己是
持有人：链接里带着签名。

- `POST /api/me/{cap}/renew` — 只在链接**最后 7 天**允许（`CAPABILITY_RENEW_WINDOW`，
  默认 `604800`）。更早续期只会延长「泄露链接还能用」的窗口，所以 403 并说明
  还剩几天。
- 续期前再确认一次 `student_credentials(sid)` 里确实有这个 hash，避免拿旧链接去
  「续」一个已经不在链上的凭证。
- 旧 token 不作废：它按自己的 `exp` 继续有效，所以持证人续期不会让已经发出去的
  链接立刻失效。
- holder 页 `#holderRenew`：剩余 ≤ 7 天才显示，文案给天数；点击后 `location.replace`
  到新链接，页面上的 PDF / QR / 公开验证都自动带新 token。

顺带修了一个真实布局问题：续期行原本复用了 `.meta` 的段落样式，在窄视口里
按钮被压成 60 px 宽、70 px 高（中文整个换行），DOM 上虽有元素却点不中。改成
`display:flex` + `white-space:nowrap` 后按钮是 162 × 27 px，可正常点击。

## 4. 验证

新增 `tests/test_u14_console.py`（12 条，integration 档）：

| 断言 | 覆盖 |
|---|---|
| 同一角色最多 3 条会话；淘汰的是最旧那条；淘汰一个角色不动另一个 | 会话上限 |
| 退出所有设备：同角色两条都失效，issuer 会话保留；无会话 401 | logout-all |
| 5 次错 token → 第 6 次 429 + `Retry-After`；限流期间正确 token 也 403/429；成功登录清零 | 登录限流 |
| 撤销前 PDF 无红框，撤销后两个版本都有 `REVOKED ON CHAIN` + 原因 | 撤销标注 |
| 30 天链接续期 403；6 天链接续期 200 且新链接可用；学号不在链上 404 | 链接续期 |

结果：

- `scripts/run_all_tests.py`：**29/29 模块全绿**（原 28 + 新模块）。
- 前端 harness：**34/34**；`tests.test_frontend` 22 条 OK。
- 8013 真实服务实测：
  - `/api/admin/pdf/<已撤销 hash>` 与 `/api/pdf/<同一 hash>` 都含红框与 `WRONG ISSUE`，
    公开版仍是 `withheld` + 0 附件。
  - 两台 admin 设备 + 一台 issuer 设备登录；admin 在设备 A 点「退出所有设备」→
    `dropped=2`，A、B 的 whoami 都变空，issuer 仍是 `issuer`。
  - 现有 223 字符 cap（剩 29 天）续期 → 403「still has 29 day(s) left」；6 天 cap
    续期 → 新链接 30 天，`/me/<新>` 200，`/api/me/<新>` 返回同一 hash。
  - 浏览器：持证人页在 6 天链接上显示「续期这个链接 / 链接将在 5 天内到期」，
    点击后续到 2026-12-20 且按钮自动隐藏。

## 5. 这一轮没做的，以及原因

- **公开页是否保留「下载验证报告」入口**：保留。它是无 PII 的报告，删掉反而让
  雇主没有可留档的东西；真正的凭证仍然只能由持证人转发。
- **`DEMO_OPEN` 默认改 0**：没改。默认 1 让 29 个模块和演示脚本无需逐个设环境变量，
  而 `/api/version` 与公开页都会明说「演示模式」。真要上线，文档里写明设 0。
- **`/api/status` 公开撤销原因**：没做。撤销原因可能带内部备注，只公开「撤销了、
  在哪个区块」更稳；原因目前只在持证人页和员工接口出现。
- **通知过滤 / 分页**：价值低，跳过。

## 6. 已知限制（继续留档）

- bu 会话这一轮出现 `viewport=0x0`：`bu.screenshot()` 报 "viewport unavailable"，
  `bu.click(ref)` 报 `kElementOffscreen`，登录表单也 `snapshot` 失败。页面文本
  读取和 `bu.js` 的 DOM 点击仍可用，所以续期流程是用 DOM 点击验证的；按钮几何
  是用 `getBoundingClientRect()` 读的。这不是页面缺陷，是浏览器后端状态。
- 8013 是演示态，链高 13；这一轮只读了已撤销的那条记录（`WRONG ISSUE`，区块
  #10），没有为了测试往演示链里写新块。
