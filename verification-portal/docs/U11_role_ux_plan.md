# U11 — 角色与入口分离计划（Role / UX separation）

> 状态：**计划，未实施**。本文件只定义要做什么、按什么顺序做、如何验收，不含代码改动。
> 触发问题：学生在门户里能看到并进入「签发 Issue」「自制 Self-issue」「注销 Revoke」「签发方 Signers」「通知发送」等教职员功能区。

---

## 1. 现状诊断（均有代码依据）

| # | 现象 | 证据 | 性质 |
|---|---|---|---|
| 1 | 所有功能 tab 对任何访客渲染，`ADMIN` 只是视觉标签 | `static/index.html:28-37`（9 个 `data-tab` 按钮，`admin-tag` 仅样式） | 前端无角色门控 |
| 2 | 未配置 `ADMIN_TOKEN` 时，签发类端点直接放行 | `app/authz.py:75-77`（`configured_roles` 为空即 `return None`）；`app/config.py:15-17`（`ADMIN_TOKEN` 默认 `None`） | 后端 fail-open |
| 3 | 默认部署即命中第 2 条：`PUBLIC_MODE` 默认 `0` | `app/config.py:40	PUBLIC_MODE = os.environ.get("PUBLIC_MODE", "0") == "1"` | 默认配置最不安全 |
| 4 | 签发面板有「学生邮箱（可选，用于通知记录）」输入框，填了就发 | `static/index.html:275`；`app/notifier.py:54-77`（`notify_issue` 用传入的 `to` 直接 SMTP 发送或记录 dry-run） | 通知可由前端任意触发，收件人不受限 |
| 5 | 学生自助查询只需「学号 + 出生日期」，无令牌、无限流 | `app/main.py:1105-1130`（`/api/student/{student_id}`，DOB 为唯一门）；`rate_limit.py` 未覆盖该路由 | 8 位 DOB 可枚举，属弱隐私门 |
| 6 | 学生面板本身是只读的，越权来自「能看到别的 tab」 | `static/index.html:175-192` | 根因在第 1 条 |

判断：**这不是缺一个 if，而是缺一套「身份 → 可见入口」的映射**。前端隐藏 + 后端放行，等于没做；只加后端 401，会让演示当场进不去签发页。两者必须一起改。

---

## 2. 目标与角色矩阵

### 2.1 三类身份

| 身份 | 如何获得 | 定位 |
|---|---|---|
| 公开访客（verifier） | 无需凭证，默认落地 | 验证他人凭证、看公开日志、问 AI 助手 |
| 学生（holder） | 持本人查询码 | 查自己的凭证、下载 PDF、查撤销状态 |
| 教职员（registrar / staff） | 登录后获得 admin/issuer 角色 | 签发、批量签发、注销、管理签发方与 API key |

### 2.2 目标矩阵（P1 落地后的期望行为）

| 能力 | 访客 | 学生 | 教职员 |
|---|---|---|---|
| `/` 落地页 | 是 | 是 | 是 |
| `/verify`、`/api/verify/*`、`/api/statuslist` | 是 | 是 | 是 |
| `/api/log`、`/api/anomalies`、`/api/chat` | 是 | 是 | 是 |
| `/api/student/{id}`（本人凭证） | 否 | 是（查询码） | 是（管理用途） |
| `/api/qr/*`、`/api/pdf/*`（本人凭证） | 否 | 是 | 是 |
| `/api/issue`、`/api/issue/batch` | 否 | 否 | 是 |
| `/api/custom/build`、`/api/revoke` | 否 | 否 | 是 |
| `/api/signers`（写）、`/api/signers/active` | 否 | 否 | 是 |
| `/api/admin/apikeys*`、`/api/admin/audit`、`/api/admin/chain-snapshot` | 否 | 否 | 是 |
| 触发邮件通知 | 否 | 否 | 仅签发动作的服务端副产物 |

前端只渲染当前身份允许的 tab；后端对越权请求一律 `403`（缺凭证）或 `401`（凭证错误）。

---

## 3. 实施阶段（按 PR 粒度，逐段验收）

### P0 · 角色矩阵与入口盘点（只读，0.5 天）

- 产出：把 §2.2 矩阵写进 `docs/U11_role_matrix.md`，逐条标注「端点 / 装饰器 / 当前行为 / 目标行为」。
- 核对 `static/js/` 里是否存在任何客户端凭证（`core.js` 的 `api()` 封装、`registrar.js` 的请求头）。
- 验收：矩阵 100% 覆盖 `main.py` 中全部 `@app.*` 路由；无遗漏、无「待定」。

### P1 · 后端 fail-closed + 角色落地（1–1.5 天）

改动面：
- `app/authz.py`：未配置任何令牌时，`require_roles` **改为拒绝**（403，文案说明「本实例未启用教职员功能」），不再 `return None`。
- `app/config.py`：新增 `STAFF_TOKEN`（或沿用 `ADMIN_TOKEN`）与「未配置即禁用」的显式开关；`PUBLIC_MODE` 语义保持「只暴露验证面」，但不再依赖它兜底安全。
- 新增 `scripts/init_staff_token.py`：首次启动生成随机 token，写入 `.env`（权限收紧），并在控制台**只打印一次**。
- `app/main.py`：不新增端点、不改现有路径与函数签名；仅确认 `_admin_required` 与 `require_roles` 的委托关系在 fail-closed 下仍覆盖全部 8 个写端点。
- `tests/`：现有夹具默认走 demo-open，需要改为「夹具显式注入 token」；新增 `tests/test_role_matrix.py`，逐行断言 §2.2。

验收：
```
访客 POST /api/issue            -> 403
学生 GET  /api/issue/batch      -> 403
教职员 POST /api/issue          -> 200
教职员 token 错误               -> 401
PUBLIC_MODE=1 + 任何 token      -> 403
```
- 全量回归走 `scripts/run_all_tests.py`（27 模块 / 310 条），不得出现状态污染式误报。

### P2 · 前端角色化入口（1–1.5 天）

改动面：
- `static/index.html`：tab 容器改为按角色渲染；`admin-tag` 标签整组迁到「教职员区」。
- 落地页 `role-grid`（`index.html:46-71`）从 4 张卡减为 3 张（Verify / Student / 教职员登录），教职员卡进入登录后不再回落地页。
- `static/js/main.js`：新增身份态（`sessionStorage` 存角色，不存明文 token）；tab 显隐、`api()` 统一附带凭证、收到 401/403 时**清空身份并回到落地页**。
- 新增教职员登录面板：单输入框 + 失败限速（复用 `rate_limit.py`）。
- 学生面板移除任何签发/发送相关控件与文案。

验收（UX 三条走查）：
1. 首次打开：只看到 Start / Verify / Student / Chat；无 Issue、无 Revoke、无 Signers、无 API key。
2. 学生查询后：只能看到自己的凭证行与下载按钮，看不到签发入口。
3. 教职员登录后：签发/注销/签发方出现；退出登录后立即消失。

### P3 · 通知发送归位（0.5–1 天）

改动面：
- `static/index.html:275`：移除「学生邮箱（可选，用于通知记录）」输入框（学生与访客都不该看到）。
- `app/notifier.py`：`notify_issue` 的收件人改为**从凭证 `PersonalParticulars` 内的邮箱取值**，不再接受任意外部字符串；无邮箱则 `skipped`，不报错。
- `app/main.py`：通知只在签发成功分支内调用（现状若已如此则只补「忽略请求体邮箱」）；审计记录带 `role:` 操作者。
- 日志页 `api/log` 与 `notifications` 记录不向前端回显完整邮箱（保留打码）。

验收：
- 教职员签发带邮箱凭证 → 收件人 = 凭证内邮箱。
- 请求体额外塞 `email` 字段 → 被忽略（有单测）。
- 访客/学生无法触发任何通知（403）。

### P4 · 学生查询最小面（1 天）

改动面：
- `app/main.py:1105`：`/api/student/{student_id}` 增加「查询码」参数（签发时生成、随凭证发给持有人），DOB 降为**第二因子**而非唯一门。
- `rate_limit.py`：对该路由按 IP + 学号双维度限速；失败统一 `404`，不区分「学号不存在 / DOB 错 / 查询码错」。
- 返回体裁剪：只回必要字段（姓名、学位、状态、hash、PDF/QR 链接），不回完整 raw 文档。
- 兼容：保留 `dob` 参数名，避免破坏既有调用；新增参数可选，未提供时行为收紧。

验收：
- 连续错误 10 次触发 429。
- 三种失败原因返回同一文案与同一状态码。
- 正确查询码 + DOB → 返回本人凭证，字段数符合白名单。

### P5 · 回归与交付（1 天）

- 全量测试 + 新增角色矩阵用例；`scripts/run_all_tests.py` 全绿。
- 手工走查三条路径并截图，替换 `docs/screenshot-*.png` 中涉及签发入口的旧图。
- 更新 `DEPLOY.md`（教职员 token 初始化步骤）、`USAGE.md`（三类身份怎么进）。
- 重录演示视频（若演示需要签发，先登录再签发）。
- 重跑 `build_package.py` 刷新 zip，确认 DOCX 与包内一致。

---

## 4. 需要你拍板的三个决策

1. **演示怎么进签发页**：教职员登录框输入 token（推荐），还是启动脚本自动在浏览器预填一次？（后者更省事，但等于把凭证交给任何打开页面的人。）
2. **`ADMIN_TOKEN` 是否改名 `STAFF_TOKEN`**：改名更贴语义，但要同步 `DEPLOY.md`、启动脚本与旧测试；不改则零迁移成本。
3. **学生查询是否引入「查询码」**：引入最安全；不引入就只能靠限速 + 统一错误，DOB 枚举风险仍在。

---

## 5. 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| fail-closed 打破现有演示脚本 | 一键启动后签发页 403 | P1 同时交付 `init_staff_token.py` 与启动脚本读 `.env`；回滚只需恢复 `authz.py` 的 `return None` 分支 |
| 现有 310 条测试大量依赖 demo-open | 大面积红 | 先改夹具（P1 第一步），再改实现；不逐条改断言 |
| 前端身份态存 `sessionStorage` | 关闭标签页即失效 | 可接受（演示场景）；不做持久登录 |
| 端点上加参数改签名 | 违反「公共 API 签名不变」红线 | P4 新增参数设为可选关键字参数，不改既有位置参数 |
| 通知收件人改绑凭证内邮箱 | 历史凭证可能无邮箱 | `skipped` 分支保留，不抛错 |

回滚策略：每个阶段独立可回退；P1/P2 必须同批上线（只做其一都会造成「隐藏了但能调」或「拦住了但进不去」）。

---

## 6. 明确不做

- 不引入 OAuth / 会话服务 / 付费鉴权组件（沿用现有共享密钥模型）。
- 不重写前端框架、不改 `api()` 之外的调用约定。
- 不改任何现有端点路径。
- 不做多租户或真实多机构注册（超出课程项目范围）。
