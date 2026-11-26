# QuantumGuard / GEF Mobile — 代码逻辑详解（Code Walkthrough）

> 面向答辩与演示视频：本文按模块逐个说明**职责、关键函数、执行逻辑、输入/输出、设计要点**，最后附每人可直接照读的讲稿口径。
> 对应代码目录：`verification-portal/`，后端为 Python + FastAPI，前端为单页原生 HTML。
> 当前版本：APP_VERSION 6.0.0；108 个自动化测试 / 12 个测试模块。

---

## 0. 项目总览

### 0.1 这个系统做什么
一所学校（签发方）把凭证（文凭 / 成绩单）的**哈希和签名**写进一条私有链；个人明文数据不上链。验证者上传凭证 JSON 或门户签发的文凭 PDF，系统跑**六项密码学检查**，给出判定：

- `VALID` —— 六项全部通过；
- `REVOKED` —— 链上存在撤销记录；
- `NOT FOUND` —— 链上找不到对应 ISSUE 块；
- `INVALID` —— 哈希 / 签名 / 签发方等任一不通过；
- `CHAIN DATA CORRUPT` —— 链文件缺失或损坏（结构化报错，不崩溃）。

只给哈希、不给完整文档时，第 4 项（哈希匹配）无法计算，返回 `VALID ON CHAIN / REVOKED / NOT FOUND / INVALID / CHAIN DATA CORRUPT`。

### 0.2 一次验证的完整生命周期（时序）

```
浏览器 static/index.html
   │  上传 PDF / JSON，或粘贴哈希
   ▼
POST /api/verify/document   （app/main.py 接口层）
   │  1. 中间件：请求体积上限 → API Key 校验 → 滑动窗口限流
   │  2. 解析上传文件：PDF 取内嵌 JSON；.json/.txt 直接解析
   │  3. 校验文档形状：嵌套深度、JSON 体积
   ▼
chain_service.verify_document(document)   （服务层）
   │  1. 检查三段必备字段；建链（幂等）
   │  2. 调用链核心六项检查；链损坏时转结构化 CORRUPT 判定
   ▼
blockchain_util.verify_document(chain_addr, document)   （链核心）
   │  1. 三段重算哈希 → Merkle 根
   │  2. 整链重放校验 → 倒序找匹配 ISSUE 块
   │  3. 签发方注册表比对 → 分段哈希比对 → 签名复核 → 撤销状态
   ▼
crypto_util   （密码学：规范化 / 哈希 / Merkle / 签名验签）
   │
   ▼
结果 JSON → 收据注册表登记 → 匿名公开日志记录 → 前端判定卡 + 可下载收据
```

签发（issue）与撤销（revoke）走同一套链核心，只是写入方向相反：签发追加 ISSUE 块，撤销追加 REVOKE 块。

### 0.3 模块地图

| 层 | 文件 | 一句话职责 |
|---|---|---|
| 接口层 | `app/main.py` | FastAPI 路由、加固中间件、上传解析、端点编排 |
| 服务层 | `app/chain_service.py` | 建链播种、签发/撤销/验证/状态、签发方管理、学生索引 |
| 链核心 | `app/blockchain_util.py` | 区块结构、注册表、追加区块、单块/整链校验、六项检查 |
| 密码学 | `app/crypto_util.py` | JCS 规范化、SHA3-512、Merkle 根、密钥、签名/验签 |
| 请求模型 | `app/schemas.py` | Pydantic 请求体模型 |
| 配置 | `app/config.py` | 全部环境变量与默认值 |
| 限流 | `app/rate_limit.py` | 内存滑动窗口限流器 |
| 雇主包 | `app/apikeys.py` | 公共 API Key 生命周期与校验（只存摘要） |
| 雇主包 | `app/receipt_registry.py` | 验证收据登记表（环形缓冲） |
| 雇主包 | `app/statuslist.py` | 签名撤销状态列表（OCSP-like，可缓存） |
| 日志 | `app/public_log.py` | 持久化匿名验证日志（jsonl） |
| 通知 | `app/notifier.py` | 签发邮件通知（默认 dry-run） |
| 风控 | `app/anomaly.py` | 签发速度异常检测（IsolationForest + 规则兜底） |
| PDF | `app/pdf_diploma.py` | 可验证文凭 PDF 渲染 + 内嵌 JSON 提取 |
| PDF | `app/pdf_extractor.py` | 证书 PDF 自动填充 JSON 草稿（输入辅助，不验签） |
| 自助定制 | `app/custom_service.py` | 自助填表生成凭证、可选上链、落盘 PDF/JSON |
| RAG | `app/rag_indexer.py` | 语料构建 + FAISS/numpy 向量索引 |
| RAG | `app/rag_embedder.py` | 文本向量嵌入（MiniLM，哈希回退） |
| RAG | `app/rag_generator.py` | 答案生成：DeepSeek → Ollama → 离线确定性引擎 |
| RAG | `app/chat_service.py` | 问答编排：检索 → 生成 → 来源 / 人物 / 联网 |
| RAG | `app/person_context.py` | 脱敏人物档案 + 会话指代记忆 |
| RAG | `app/web_research.py` | 人物公开信息检索（仅姓名+机构，单独标注） |
| 前端 | `static/index.html` | 单页响应式双语 UI，无框架 |
| 脚本 | `scripts/` | 批量核验 CLI、链备份、演示视频、冒烟测试、测试运行器 |
| 测试 | `tests/` | 12 模块 108 用例，每条用例使用隔离的临时链 |

---

## 1. `app/crypto_util.py` —— 密码学原语

### 1.1 职责
所有规范化、哈希、Merkle 树、密钥生成/存取、签名与验签都集中在这里。链核心和服务层只调用本模块的函数，不直接碰加密库。

### 1.2 设计前提（来自凭证结构规范）
- **规范化（JCS, RFC 8785）**：同一个 JSON 对象，无论键的书写顺序如何，序列化出的字节永远相同。否则同一个凭证可能哈希出不同结果。
- **哈希算法**：链默认 `sha3_512`；摘要输出 **base64url 且去掉填充 `=`**。
- **签名对象不是凭证哈希本身**：先用 nonce 对 `payloadHash` 做 HMAC，再用私钥签这条 HMAC 消息。nonce 是随机的，因此同一凭证每次签名结果都不同，避免重放/确定性签名暴露问题。
- **签发方身份**：用公钥的 X.509 SubjectPublicKeyInfo（SPKI）DER 编码做 SHA-1 / SHA-256 指纹（colon-separated hex），注册表按指纹匹配。

### 1.3 函数逐个说明

| 函数 | 输入 | 逻辑 | 输出 |
|---|---|---|---|
| `json_rfc8785(obj)` | JSON 对象 | 调用 `jcs.canonicalize` 做规范序列化 | 规范字节 / 字符串 |
| `hash_json(json_input, hashalgo="sha3_512")` | JSON 对象 | 规范化 → 取哈希对象 → 更新规范字节 → base64url 去填充 | 摘要字符串 |
| `hash_bytes(data, hashalgo)` | 原始字节 | 直接哈希字节（供 Merkle 合并使用） | 摘要字符串 |
| `merkle_root(leaf_hashes, hashalgo)` | 叶子摘要列表 | 逐层两两合并；奇数个时最后一个叶子复制补位；每层把左右摘要拼接后再哈希，直到剩一个根 | Merkle 根摘要 |
| `gen_dskey(algo)` | 算法字符串 | 按前缀分派：`ML_DSA_44/65/87` 后量子；`RSA-2048/3072/4096/8192/15360`；`ec.SECP256R1/384R1/BRAINPOOLP256R1/384R1`；不支持的算法抛 `ValueError` | `(私钥, 公钥)` |
| `ds_algo_of_key(priv_key)` | 私钥对象 | 按类型反查人类可读算法名（RSA-位数 / ec.曲线 / ML_DSA_位数） | 算法字符串，未知为 `UNKNOWN` |
| `getfgpt(pub_key)` | 公钥 | 导出 SPKI DER → 分别算 SHA-1、SHA-256，转 colon hex | `(sha1fgpt, sha256fgpt)` |
| `save_privkey / save_pubkey` | 密钥 + 路径 | 私钥 PKCS8 PEM（可加密口令）；公钥 SPKI PEM；写文件 | 无 |
| `fetch_privkey / fetch_pubkey` | 路径 + 口令 | 先按 PEM 加载，失败再按 DER 加载 | 密钥对象 |
| `_hmac_b64(payload_hash, nonce, algo)` | 载荷哈希、nonce、哈希算法 | 以 nonce 为 key、载荷哈希为消息做 HMAC → base64url 去填充 | HMAC 消息串 |
| `sign_json(json_input, ds_algo, private_key, content_hash_algo, nonce=None)` | 凭证 JSON、算法、私钥 | ① 算 `payloadHash`；② 无 nonce 则生成 32 字节 urlsafe 随机数；③ 构造 HMAC 消息；④ 按私钥类型分派：ML-DSA 直签、RSA 用 PSS（MGF1 + 对应哈希）、ECDSA 曲线哈希；⑤ 签名 base64url 去填充 | `(nonce, 签名串)` |
| `verify_ds(json_input, ds_algo, public_key, signature_b64, nonce, content_hash_algo)` | 待验 JSON、公钥、签名、nonce | ① 重算 `payloadHash` 与 HMAC 消息；② 补全 base64url 填充后解码签名；③ 按公钥类型分派验签；④ 任何异常都返回 `False`，不抛异常给上层 | `True / False` |

### 1.4 设计要点与答辩口径
- **后量子定位**：默认签发方是 ML-DSA-65（FIPS 204 后量子签名），同时兼容 RSA-PSS 与 ECDSA；凭证寿命长达数十年，选型面向未来量子计算威胁。
- **验签失败不抛异常**：`verify_ds` 把所有异常收敛为 `False`，避免恶意构造的签名把服务打崩。
- **可讲的一句**："我负责密码学模块：先把 JSON 规范化，三段分别做 SHA3-512 哈希，再用 Merkle 根合成凭证指纹；签发时用随机 nonce 把载荷哈希做 HMAC 后再签名，验签时按同样路径重算并用注册表公钥复核。"

---

## 2. `app/blockchain_util.py` —— 私有链核心

### 2.1 职责
实现链的存储结构、可信签发方注册表、区块追加、单块校验、整链重放，以及对外最重要的 `verify_document` 六项检查。

### 2.2 磁盘存储结构

```
<CHAIN_DIR>/
├── info.yaml                 # 链元数据 + 可信签发方注册表
├── blocks/
│   ├── block-000000000.json  # 创世块（height 0）
│   └── block-000000001.json  # 普通块（先写 .temp 再原子改名）
├── rawjsondocs/
│   └── <HashedDocument>.json # 链外明文索引（供 RAG 与学生查询，不在链上）
└── keys/                     # 签发方公钥 PEM；私钥仅演示环境存放于此
```

### 2.3 区块结构

| 字段 | 含义 |
|---|---|
| `height` | 块高度，与文件名编号一致 |
| `contentHashAlgo` | 内容哈希算法（默认 `sha3_512`） |
| `prevHashSum` | 上一个区块整体 JSON 的哈希（创世块为空串） |
| `timestamp` | 纳秒时间戳 |
| `payload` | 动作载荷：ISSUE / REVOKE；**只放哈希与必要的 DocumentInfo，不放个人明文** |
| `DataSignatureInfo` | 每个签名方一条：指纹、版本、算法、nonce、签名 |

### 2.4 函数逐个说明

#### 2.4.1 元数据读写
- `read_info(chain_addr)`：读 `info.yaml`；文件缺失或 YAML 损坏抛 `ChainDataError`。
- `write_info(chain_addr, info)`：先写 `.temp` 再 `os.replace` 原子改名，避免半截文件损坏注册表。

#### 2.4.2 初始化
- `init_block(chain_addr, chain_name, content_hash_algo, overwrite=False)`：建目录与创世块；创世块 `prevHashSum` 为空、时间戳固定 0，因此同链名总是从同一根开始；`info.yaml` 写入链名、算法、高度 0、空注册表。

#### 2.4.3 可信签发方注册表
- `register_signer(chain_addr, name, pub_key, ds_algo)`：算指纹 → 去重加入 `trusted_signers` → 保存公钥 PEM 到 `keys/`。
- `trusted_signers(chain_addr)`：返回注册表列表。
- `is_trusted(chain_addr, sha256fgpt)`：指纹是否在注册表内。

#### 2.4.4 载荷构造
- `issue_payload(document, algo)`：
  1. 校验三段必备字段存在；
  2. 分别哈希 `PersonalParticulars / AcademicInfo / DocumentInfo`；
  3. 三段叶子走 Merkle 根得到 `HashedDocument`；
  4. 载荷含四段哈希 + 回显的 `DocumentInfo`（机构、类型、签发日期等非敏感展示信息）。
- `revoke_payload(hashed_document, algo)`：只记录动作 `REVOKE` 与被撤销凭证指纹；撤销原因与生效日期由服务层附加。

#### 2.4.5 区块读写
- `_block_path(chain_addr, height)`：`blocks/block-{9 位编号}.json`。
- `_write_block_file(chain_addr, block)`：`.temp` 写盘后原子改名。
- `load_block(chain_addr, height)`：读区块 JSON；文件缺失/损坏抛 `ChainDataError`，供上层区分"数据坏了"和"块没问题"。
- `last_height(chain_addr)`：从 `info.yaml` 读最后高度。

#### 2.4.6 追加区块 `append_block(chain_addr, payload, signers, content_hash_algo)`
1. 至少需要一个签名方；
2. 读链元数据，高度 = 上次高度 + 1；
3. 加载上一块并算其整体哈希作为 `prevHashSum`；
4. 对每个 `(算法, 私钥)` 调用 `sign_json`，记录指纹、算法、nonce、签名；
5. 组装区块（纳秒时间戳），写块文件，更新 `info.yaml` 高度；
6. 返回新区块字典。

#### 2.4.7 签名复核 `_verify_payload_signatures(chain_addr, block)`
对 `DataSignatureInfo` 每条：
1. 指纹不在注册表 → 记 "untrusted signer"；
2. 取注册表公钥，调 `verify_ds` 复核；
3. 签名无效 → 记 "signature invalid"；算法与注册表登记不一致 → 记 "algorithm mismatch"。
返回 `(全部通过?, 问题列表)`。

#### 2.4.8 单块校验 `verify_block(chain_addr, height)`
不抛异常，返回每一项布尔值：
- `next_link`：下一块的 `prevHashSum` 是否等于本块哈希（链尾块视为通过）；
- `prev_link`：本块 `prevHashSum` 是否等于上一块哈希（创世块要求为空串）；
- `height`：文件内高度与编号一致；
- `signatures`：载荷签名全部可信且有效。
任一不过则 `ok=False`。

#### 2.4.9 整链校验 `verify_chain(chain_addr)`
从创世块逐块调用 `verify_block`，**不提前退出**，一次列出所有问题；返回 `(是否全部通过, 逐块报告)`。

#### 2.4.10 状态查询 `fetch_status(chain_addr, hashed_document)`
遍历块找动作与指纹匹配的记录，返回：
```
{ issued, revoked, issue_heights: [...], revoke_heights: [...] }
```

#### 2.4.11 六项检查 `verify_document(chain_addr, document)`
1. 对出示凭证三段重算分段哈希与 Merkle 根 `h_doc`；
2. **链完整性**：整链重放通过；
3. **链上有记录**：从最高块倒序找匹配 `h_doc` 的 ISSUE 块；
4. 找到后：**签发方可信**（块上每个签名指纹都在注册表）；**哈希匹配**（三段分段哈希与 Merkle 根与链上载荷一致）；**签名有效**（复核 ISSUE 块签名）；找不到块时这三项置 `False`；
5. **未撤销**：`fetch_status` 无 REVOKE 记录；
6. 六项全为 `True` 才 `valid=True`。

### 2.5 设计要点与答辩口径
- **明文不上链**：链载荷只存哈希；明文副本在链外 `rawjsondocs/`，服务层可单独替换为数据库。
- **防篡改靠哈希链 + 签名链双重约束**：改历史块会同时断掉前后哈希链接线，并使签名复核失败。
- **损坏数据不 500**：缺失/损坏块被包装成 `ChainDataError`，上层转结构化判定。
- **可讲的一句**："我负责链核心：每个块记录上一块哈希并由签发方签名；验证时先整链重放，再按指纹倒序定位 ISSUE 块，核对分段哈希、签名与撤销状态，六项全过才判 VALID。"

---

## 3. `app/chain_service.py` —— 服务层

### 3.1 职责
夹在 FastAPI 接口层与链核心之间：启动建链播种、加载/切换签发方、签发、撤销、封装文档验证与哈希验证、撤销元数据、快照标识、签名任意载荷、多签发方管理、学生自助索引。线程可重入锁 `RLock`。

### 3.2 内置样例凭证
- `SAMPLE_DIPLOMA`：学位文凭样例（虚构人物）；
- `SAMPLE_TRANSCRIPT`：成绩单样例（含课程列表、GPA/CGPA）；
- `SAMPLE_REVOKED_DOC`：公开模式用的"已签发且已撤销"样例，保证幂等。

### 3.3 函数分组说明

#### 3.3.1 签发方与密钥
- `_ensure_signer()`：注册表为空时生成默认算法密钥对（默认 ML-DSA-65），私钥落 `keys/`，公钥写入注册表。
- `_load_signer()`：读取当前激活签发方；未显式激活则取第一个；私钥文件缺失抛清晰错误。
- `_active_signer_fgpt()`：从 `active-signer.json` 读激活指纹；文件缺失返回 `None`。
- `add_signer(name, ds_algo)`：生成新密钥对 → 注册 → 返回记录（含是否激活标记）。
- `set_active_signer(sha256fgpt)`：指纹必须已注册，写入 `active-signer.json`。
- `list_signers()`：注册表 + 当前激活指纹。

#### 3.3.2 建链与播种
- `_store_raw_document(document, hashed_document)`：明文 JSON 存到 `rawjsondocs/<hash>.json`，供 RAG 检索与学生查询。
- `_seed_samples()`：用当前签发方把两份样例凭证上链并保存明文。
- `ensure_chain()`：幂等；无 `info.yaml` 时初始化 + 注册签发方 + 播种；已存在则补注册缺失签发方。
- `ensure_revoked_sample()`：公开模式样例；先建链，若无签发记录则签发，若无撤销记录则追加撤销块；重复调用不重复写。
- `restore_snapshot_if_needed(url)`：免费层持久化钩子；链目录为空且配置了快照 URL 时下载 tar.gz 恢复；**成员路径校验**：拒绝绝对路径与 `..`，防止快照越界写盘；恢复后必须有 `info.yaml`。

#### 3.3.3 签发 / 撤销
- `hash_of(document)`：直接返回凭证链上指纹（不上链）。
- `issue(document)`：建链 → 取激活签发方 → 构造 ISSUE 载荷 → 追加块 → 存明文；返回指纹、高度、区块。
- `revoke(hashed_document, reason=None, effective_at=None)`：构造 REVOKE 载荷，可选附加撤销原因（截断 200 字符）与生效时间戳；追加块。
- `revoked_records()`：遍历块取每个指纹最新一条 REVOKE 记录（指纹、高度、原因、生效时间），按指纹排序，供签名状态列表使用。
- `revoke_meta(hashed_document)`：单条撤销元数据，无则空字典。

#### 3.3.4 验证封装
- `status(hashed_document)`：透传 `fetch_status`。
- `verify_document(document)`：先校验三段字段；调链核心验证；捕获 `ChainDataError` 转 `_corrupt_verdict`；按结果映射 `VALID / REVOKED / INVALID`。
- `verify_hash(hashed_document)`：无完整文档可算第 4 项；重放整链 → 倒序找 ISSUE 块 → 签发方可信与签名有效可算，`hash_match=None`；生命周期查撤销；判定映射 `REVOKED / NOT FOUND / VALID ON CHAIN / INVALID`；损坏链转 CORRUPT。
- `_corrupt_verdict(exc, hashed_document)`：结构化损坏判定，含 `chain_error` 原因。

#### 3.3.5 快照标识与签名
- `chain_snapshot_id()`：`"<高度>:<末块哈希前 24 位>"`；链不变标识不变，供状态列表缓存判断；尾部损坏也返回兜底标识。
- `sign_payload(payload)`：用激活签发方签任意载荷，返回 `(算法, 签名串)`，供状态列表签名。

#### 3.3.6 查询与索引
- `demo_credentials()`：两份样例的文档与指纹，供前端试按按钮。
- `chain_tail(limit)`：链尾 N 块的匿名摘要（动作、12 位哈希前缀、时间戳、签发方指纹前缀）。
- `student_credentials(student_id, dob=None)`：在链外 `rawjsondocs/` 按学号匹配；可选出生日期门禁；返回每条凭证类型、学位、高度、撤销状态、判定。

### 3.4 设计要点与答辩口径
- 服务层不实现密码学，只做编排、校验包装与状态映射；链核心可独立复用。
- 所有写操作在锁内进行，避免并发追加块高度冲突。
- **可讲的一句**："我负责服务层：启动时幂等建链并播种样例；签发/撤销经激活签发方签名上链；验证分文档级与哈希级两条路径，链损坏时返回结构化 CORRUPT 而不是报错崩溃。"

---

## 4. `app/main.py` —— FastAPI 接口层

### 4.1 职责
装配应用、加固中间件、鉴权依赖、输入校验、所有 HTTP 端点、上传文件解析。前端页面由静态文件返回。

### 4.2 启动与全局常量
- `HASH_RE`：base64url 哈希格式正则（16–200 字符，无填充）。
- `SIX_CHECKS`：六项检查字段名元组。
- `_public_limiter / _admin_limiter`：两个滑动窗口限流器；`_EXEMPT_PATHS`：`/`、`/healthz`、`/api/version` 不限流。
- `_lifespan`：启动时先尝试快照恢复，再 `ensure_chain()`。

### 4.3 加固中间件 `_hardening_middleware`
按顺序：
1. **体积上限**：`content-length` 超过 `MAX_BODY_BYTES`（6 MB）直接 413；
2. **API Key 校验**：解析 `Authorization: Bearer <key>`，命中有效 Key 用该 Key 独立限流桶；Key 无效/已撤销返回 401；
3. **限流分桶**：匿名流量按 IP（优先 `X-Forwarded-For` 首段）；管理员路径（`/api/issue`、`/api/revoke`）用管理员桶（30 次/分）；Key 持有者用更高额度（`API_KEY_MAX`，默认 600 次/分）；匿名公开桶 120 次/分；超限 429。

### 4.4 鉴权与校验辅助
- `_admin_required`：`PUBLIC_MODE=1` 时所有管理端点 403；配置了 `ADMIN_TOKEN` 时校验 `X-Admin-Token` 头，缺失/不符 401。
- `_validate_hash`：哈希格式不符 422。
- `_json_depth(value, _depth)`：递归统计 JSON 嵌套深度。
- `_validate_document_shape(document)`：深度超 50 或序列化体积超 2 MB 抛 `ValueError`，防御"zip bomb"式深嵌套文档。

### 4.5 上传解析 `_parse_upload(raw, filename)`
- `.pdf` 或字节头 `%PDF` → 调 `pdf_diploma.extract_credential` 取内嵌 JSON；
- 非 `.json/.txt` 且文本不以 `{` 开头 → 不支持的文件类型；
- 文本解析为 JSON 对象，否则报错。

### 4.6 端点清单与逻辑

| 方法 | 路径 | 逻辑要点 |
|---|---|---|
| GET | `/` | 返回 `static/index.html` 单页 UI |
| GET | `/healthz` | 链名、算法、高度、签发方；供平台健康检查 |
| GET | `/api/version` | 应用名、版本、公开模式、验证专用模式、基础 URL、运行时长、链摘要、状态列表摘要 |
| POST | `/api/issue` | 管理端；调 `chain_service.issue`；可附学生邮箱触发通知 |
| POST | `/api/issue/batch` | 批量签发；逐行独立处理，坏行只报本行错误，不回滚好行；上限 `BATCH_ISSUE_MAX`（默认 200） |
| POST | `/api/custom/build` | 自助定制：填表 → 生成 JSON → 可选上链 → 渲染 PDF/JSON 落盘 |
| GET | `/api/custom/list` | 已生成文件列表（新到旧） |
| GET | `/api/custom/file/{file_id}/{kind}` | 按标识取 PDF/JSON；标识格式校验防路径逃逸 |
| POST | `/api/revoke` | 管理端；可给哈希或完整文档（由哈希派生）；带原因与生效日期 |
| GET | `/api/verify/{hash}` | 哈希级判定；附加撤销元数据 |
| GET | `/api/status/{hash}` | 原始生命周期：签发/撤销与高度 |
| POST | `/api/verify/document` | 文档级判定：JSON body 或 multipart 上传；解析 → 形状校验 → 服务层验证 → 登记收据 → 记公开日志；异常映射 422/413/415 |
| POST | `/api/extract/pdf` | PDF 自动填充；必须 multipart；字节头校验 `%PDF`；返回 JSON 草稿 + 置信度 + 警告；**不产生判定** |
| POST | `/api/verify/batch` | 雇主批量核验：最多 500 哈希；逐行跑哈希验证、登记收据、汇总计数；坏行记 ERROR 不中断 |
| GET | `/api/statuslist` | 签名撤销状态列表；ETag 协商缓存 |
| GET | `/api/receipt/{id}` | 收据注册表反查 |
| GET/POST/DELETE | `/api/admin/apikeys[/{id}]` | Key 创建/列表/撤销（管理端） |
| GET | `/api/pdf/{hash}` | 下载可验证文凭 PDF |
| GET | `/api/student/{id}?dob=YYYYMMDD` | 学生自助查询（出生日期门禁） |
| GET/POST | `/api/signers`、`POST /api/signers/active` | 签发方列表/注册/切换 |
| GET | `/api/notifications` | 最近通知（含 dry-run 记录） |
| POST | `/api/chat` | RAG 问答（见第 12 节） |
| GET | `/api/chat/suggestions` | 建议问题 chips |
| GET | `/api/rag/status` | 嵌入器/生成器后端与索引规模 |
| GET | `/api/demo/credentials` | 样例凭证与哈希 |
| GET | `/verify`、`GET /api/qr/{hash}` | 扫码落地页；二维码 PNG（编码公开验证链接） |
| GET | `/api/log` | 匿名验证日志 + 链尾 |
| GET | `/api/anomalies` | 异常检测结果 + 24 小时直方图 |

### 4.7 设计要点与答辩口径
- 接口层负责"边界安全"：体积、深度、格式、鉴权、限流；业务规则全部下沉到服务层与链核心。
- 上传与解析分离：`extract/pdf` 只填表单草稿，真正判定必须走 `verify/document`，自动填充不能绕过六项检查。
- **可讲的一句**："我负责接口层：FastAPI 中间件先拦大文件、校验 API Key 并分桶限流；端点把上传的 PDF/JSON 解析成标准凭证，交给服务层验证，结果登记收据和匿名日志后返回前端。"

---

## 5. `app/schemas.py` —— 请求体模型

| 模型 | 字段 | 用途 |
|---|---|---|
| `IssueBody` | `document: dict`，`student_email: Optional[str]` | 单条签发请求 |
| `BatchIssueItem` | `document: Any`，`student_email: Optional[str]` | 批量中的一行；行内形状校验在端点做，避免坏行拖垮整批 |
| `IssueBatchBody` | `credentials: List[BatchIssueItem]` | 批量签发请求 |
| `AddSignerBody` | `name="NEW SIGNER"`，`ds_algo="ML_DSA_65"` | 注册新签发方 |
| `ActiveSignerBody` | `sha256fgpt: str` | 切换激活签发方 |
| `RevokeBody` | `hashed_document` / `document` 二选一，`reason`、`effective_at` | 撤销请求 |
| `ChatBody` | `question: str`，`session_id`、`web: Optional[bool]` | RAG 问答；会话锚定上下文；`web` 强制联网检索 |

**逻辑要点**：Pydantic 只做结构承载；严格字段校验放在服务层/端点，以便批量场景逐行报错。

---

## 6. `app/config.py` —— 环境配置

所有阈值与开关由环境变量覆盖，默认值写在本模块。分组：

- **链与身份**：`CHAIN_DIR`、`CHAIN_NAME`、`SIGNER_NAME`、`SIGNER_ALGO`、`ADMIN_TOKEN`、`PUBLIC_BASE_URL`、`APP_VERSION`。
- **输入防护**：`MAX_UPLOAD_BYTES` 5 MB、`MAX_JSON_BYTES` 2 MB、`MAX_BODY_BYTES` 6 MB、`MAX_JSON_DEPTH` 50。
- **限流**：`RATE_LIMIT_ENABLED`、公开/管理员每分钟额度。
- **模式**：`PUBLIC_MODE`（只验不签发）、`UI_VERIFY_ONLY`（前端只留验证/AI/日志三页）。
- **雇主包**：`API_KEY_MAX`、`RECEIPT_REGISTRY_CAP` 5000、`STATUSLIST_MAX_ENTRIES` 20000、`BATCH_ISSUE_MAX` 200。
- **RAG**：`EMBED_MODEL`（all-MiniLM-L6-v2）、`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE/MODEL`、`OLLAMA_BASE_URL/MODEL`。
- **通知**：`EMAIL_ENABLED`、`SMTP_HOST/PORT/USER/PASSWORD`、`EMAIL_FROM`。
- **持久化**：`CHAIN_SNAPSHOT_URL`（启动恢复快照）。
- **其他**：`ANOMALY_ISSUE_PER_HOUR`、`CUSTOM_OUTPUT_DIR`、`SOFT_OCR`、`WEB_RESEARCH_ENABLED`、`WEB_RESEARCH_MOCK`。

**逻辑要点**：代码里不硬编码环境相关值；同一套代码按环境变量跑私有演示、公开验证、联网/离线 AI 三种形态。

---

## 7. `app/rate_limit.py` —— 滑动窗口限流

### 7.1 职责
单进程内存限流器，演示规模适用；多 Worker 生产环境应换 Redis。

### 7.2 逻辑
- `SlidingWindowLimiter(window_seconds=60)`：每个 key 一个 `deque` 存时间戳，线程锁保护。
- `allow(key, limit)`：
  1. `limit <= 0` 直接放行；
  2. 取单调时钟时间；
  3. 清掉窗口外的旧时间戳；
  4. 队列长度已达上限 → 拒绝；否则记录本次时间戳；
  5. 哈希表超过 2048 个 key 时，按窗口截断清理陈旧 key，控制内存。

**设计要点**：滑动窗口比固定窗口更平滑；拒绝时不写队列；内存有界。

---

## 8. 雇主包（Employer Pack）

### 8.1 `app/apikeys.py` —— 公共 API Key
- 存储：`data/apikeys.json`，线程锁；写盘先 `.tmp` 再改名。
- `_digest(key)`：`"gef26-apikey:" + key` 做 SHA-256 摘要；**只存摘要，不存明文 Key**，存储泄露不等于凭证泄露。
- `create_key(name)`：生成 32 字节 urlsafe 随机 Key + 3 字节 hex 标识；明文 Key 只在创建时返回一次。
- `list_keys()`：公开视图只含标识、名称、创建时间、最近使用、是否撤销；不含摘要与明文。
- `revoke_key(kid)`：标记撤销。
- `validate_key(key)`：摘要比对；已撤销返回 `None`；命中则更新 `last_used_at`，返回 `{id}`。

### 8.2 `app/receipt_registry.py` —— 收据登记表
- 存储：`data/receipts.json`，列表环形缓冲到 `RECEIPT_REGISTRY_CAP`（默认 5000）。
- `register(hashed_document, verdict, verified_at, endpoint)`：生成收据号 `RCP-<时间十六进制>-<2 字节 hex 大写>`；追加记录，超长截掉最旧条目；返回收据号。
- `get(receipt_id)`：按收据号反查，不存在返回 `None`。
- **用途**：雇主事后可核对"这张收据是不是本验证方签发的"，无需重新验链。

### 8.3 `app/statuslist.py` —— 签名撤销状态列表（OCSP-like）
- 结构：`schema`、生成时间、链快照（链名/高度/末块哈希/哈希算法）、撤销计数、撤销列表（哈希、原因、生效时间）。
- 缓存：以 `chain_snapshot_id()` 为键；链未变直接返回缓存，降低负载。
- 签名：调 `chain_service.sign_payload` 用激活签发方签整个载荷；ETag 由载荷哈希前 32 位生成，支持 `304` 协商缓存。
- **信任模型**：雇主可缓存这份签名列表，离线回答"是否已撤销"，下次刷新再更新；与证书吊销列表（CRL）/ OCSP 同类。

---

## 9. 日志、通知与风控

### 9.1 `app/public_log.py` —— 匿名公开日志
- 持久化到 `public-log.jsonl`，内存双端队列保留最近 50 条；文件超过 2000 行/512 KB 时重写尾部。
- `record(hashed_document, verdict)`：只记 12 位哈希前缀、判定、时间戳；**不存完整凭证与明文**。
- 文件不可写时退化为纯内存模式，不影响主流程。
- `recent(limit)` / `total()`：供日志页与测试读取。

### 9.2 `app/notifier.py` —— 签发通知
- 默认 dry-run：无邮件服务器时把"本应发送"的消息记到 `notifications.jsonl`，功能可端到端演示与测试。
- `notify_issue(to, hashed_document, doc_type)`：无收件人跳过；构造主题与正文（含链上哈希与验证链接）；配置了 SMTP 时走 `_send_smtp`（STARTTLS，可选登录）；成功记 `sent`，失败记 `error` 与原因，否则记 `dry-run`。
- `recent_notifications(limit)`：读最近通知记录。

### 9.3 `app/anomaly.py` —— 签发速度异常检测
- 统计口径：遍历 ISSUE 块，按签发方 + 小时（纳秒时间戳 → 秒 → 小时桶）计数，记录每桶末块高度。
- **规则兜底** `_rule_flags`：单签发方单小时达阈值（默认 20）即标记；达 3 倍阈值为 `high`，否则 `mild`。
- **IsolationForest** `_isolation_flags`：每个签发方样本数 ≥ 6 才拟合；`n_estimators=64`、`contamination=0.15`、固定随机种子、单线程；预测为 -1 的点标记；sklearn 缺失返回 `None` 回退规则。
- `_merge_flags`：按（签发方, 小时）合并两组标记，原因取并集，计数与高度取最大值，按计数降序。
- `detect(chain_addr)`：返回检测方法、阈值、异常列表、最近 24 小时每小时签发直方图。

**设计要点**：双检测器合并，任何一条命中都进列表并标明命中原因；环境缺依赖时功能不崩。

---

## 10. PDF 模块

### 10.1 `app/pdf_diploma.py` —— 可验证文凭 PDF

#### 渲染 `render_diploma_pdf(document, hashed_document, base_url) -> bytes`
1. A4 画布，20 mm 边距；头部色带写机构与部门；标题写凭证类型；
2. 逐行渲染：姓名、学号、出生日期、学位、修读区间、荣誉/备注、签发日期、签名人；长文本贪心换行；
3. 哈希框打印链上 SHA3-512 指纹（分两行）；
4. 可选二维码：编码 `{base_url}/verify?hash=...`，缺失 `qrcode` 库时跳过（仅装饰）；
5. 页脚注明"PDF 内嵌精确 JSON，验证走密码学判定，不做 OCR"；
6. 用 pypdf 把 `credential.json` 作为嵌入文件附加；JSON 用 `ensure_ascii=True` 转义，保证中文姓名在 Latin-1 附件编码下不损坏，`json.loads` 可还原同一字典。

#### 提取 `extract_credential(raw) -> dict`
1. `PdfReader` 打开 PDF；打不开给友好错误（提示只支持门户签发 PDF，可改传 JSON）；
2. 找附件 `credential.json`；缺失同样报错；
3. 取附件字节并解析 JSON；损坏抛"内嵌 JSON 损坏"。

**设计要点**：可验证性来自内嵌精确 JSON，而不是扫描文字；版面像素是否精美不影响判定准确性。

### 10.2 `app/pdf_extractor.py` —— PDF 自动填充（输入辅助）

#### 两种模式
1. `embedded_payload`：先尝试 `pdf_diploma.extract_credential`，成功即字节精确提取，置信度 1.0；
2. `text_extract`：无内嵌载荷的电子版证书，按标签正则从文本层抽字段，逐字段给置信度。

#### 文本抽取逻辑
- `_FIELD_RULES`：每条规则 = 标签正则 + 值正则 + JSON 字段 + 提示类型；覆盖中英文标签：姓/名、学号、性别、出生日期、学位、荣誉、签发机构、院系、凭证类型、签发日期、签名人、通用姓名、修读区间。
- `_PERIOD_RULES`：`Period: A → B`、`From A`、`To B` 三种区间写法。
- `_clean`：去尾部逗号与空白；`_norm_date`：`2022-09-01 / 2022/9/1 / 2022年9月1日 / 20220901` → `20220901`；只识别到部分日期时 `ok=False` 并给警告。
- `_extract_text(raw)`：逐页提取文本；无文本层（扫描件/图片）抛友好错误，提示改传 JSON 或手填。
- `extract_text_fields(raw)`：
  1. 标签命中后在其后 300 字符内取值；
  2. 字段置信度：标签直配 0.95，区间/日期 0.9，通用姓名 0.7；
  3. 组装三段标准 JSON；缺字段就留空，**绝不编造**；
  4. 低置信度与缺失字段写入 `warnings`；整体置信度低于 0.75 追加总体核对警告；
  5. 未识别到学号/姓名/学位/机构时逐条提示手填。
- `extract_from_pdf(raw)`：先内嵌载荷，失败转文本抽取。

**边界（必须在答辩中讲清）**：本模块只产生 JSON 草稿；不提交验证、不绕过六项检查；扫描件不做 OCR 猜测。

---

## 11. `app/custom_service.py` —— 自助凭证定制

### 11.1 职责
让有签发权限的人填表生成标准凭证 JSON，可选直接上链，并把 PDF + JSON 同步保存到项目目录；之后上传该 PDF 即可直接验证。

### 11.2 逻辑
- `_FIELD_DEFAULTS`：性别、起止日期、凭证类型、机构等兜底默认值；空值不编造姓名/学号/学位。
- `_clean`：去空白；`_norm_date`：去除 `-/.年/月/日` 等分隔归一为数字串。
- `build_document(fields)`：
  1. 姓名：优先姓 + 名；都没有时用单字段 `name`；两者都缺抛中文提示；
  2. 学号、学位必填，缺失抛提示；
  3. 组装 `PersonalParticulars / AcademicInfo / DocumentInfo` 三段标准结构。
- `_output_dir()`：目标目录先建并做写入探针（写临时点再删）；不可写时回退到门户内 `custom_outputs`。
- `_safe_id(student_id, ts)`：清理非法字符，取前 24 位 + 时间戳作文件标识。
- `build_outputs(fields, base_url, issue=True)`：
  1. 生成标准文档；算指纹；
  2. `issue=True` 时调 `chain_service.issue` 上链并取高度；`False` 时只出草稿（未上链，验证为 NOT FOUND）；
  3. 渲染 PDF；落盘 `<file_id>.pdf` 与 `<file_id>.json`；
  4. 返回文件标识、文档、指纹、高度、是否上链、PDF/JSON/验证链接、输出目录与说明文案。
- `list_outputs()`：按文件名新到旧列出 PDF/JSON 链接。
- `resolve_file(file_id, kind)`：标识必须匹配安全正则；解析后校验父目录未逃逸出输出目录且文件存在。

**诚实边界**：签发仍是管理端动作；公开验证模式下端点 403，前端隐藏自助签发页。

---

## 12. RAG / GenAI 层

### 12.1 管线总览

```
question
  → 精确查找（哈希 / 学号 / 姓名，优先固定）
  → MiniLM-L6-v2 嵌入（不可用时哈希回退嵌入）
  → FAISS IndexFlatIP 余弦检索（无 faiss 时 numpy 暴力余弦）
  → 生成器：DeepSeek API → Ollama 本地模型 → 离线确定性引擎
  → 答案 + 引用来源 + 脱敏人物档案 +（可选）联网公开结果
```

### 12.2 `app/rag_embedder.py` —— 嵌入器
- `EMBED_MODEL` 默认 `sentence-transformers/all-MiniLM-L6-v2`（CPU）。
- `_try_load_sentence_transformer()`：局部导入模型；任何失败返回 `None`，不抛异常。
- `Embedder`：
  - 加载成功：维度取自模型，后端名带模型名；`encode` 返回 L2 归一化 float32 向量；
  - 失败：1024 维哈希嵌入，后端 `hash-ngrams-v1`。
- `_hash_encode`：小写字母数字分词，MD5 取模落到 1024 桶计数，最后 L2 归一化；零外部依赖，保证无网络/无模型时检索仍可跑（质量降低）。

### 12.3 `app/rag_indexer.py` —— 语料与索引
#### 语料构建
- `credential_entry(document, hashed_document)`：把凭证拼成可读文本（姓名、学号、出生日、学位、课程、GPA、签发机构、类型、哈希），带 `id/kind/哈希/学号/姓名` 等元数据。
- `build_corpus(chain)`：三类条目——
  1. 一条链信息记录（链名、算法、高度、签发方）；
  2. 每个块一条（高度、动作、哈希、机构、类型、签发日期、签名方指纹前缀；REVOKE 记撤销指纹）；
  3. 每个 `rawjsondocs/*.json` 一条凭证条目。

#### 索引生命周期
- `RagIndex`：进程内单例；`_current_stamp()` 取链高度 + 相关文件修改时间作为版本戳。
- `ensure_ready()`：版本戳未变且索引已建直接复用；否则 `_rebuild()` 重建。
- `_rebuild()`：建语料 → 嵌入全部文本 → 建向量索引；按哈希建 `_by_hash` 映射。
- `_build_vector_index(vectors, dim)`：有 faiss 用 `IndexFlatIP`；否则返回 `None` 走 numpy 兜底。

#### 检索 `search(query, k=6)`
1. **精确哈希命中**：正则提取 40 位以上哈希 token，直接从 `_by_hash` 取条目，分数 1.0；
2. **向量检索**：查询嵌入 → FAISS/numpy 取 top-k；去重后合并；
3. 返回前 k 条视图（id/kind/text/score/高度/动作/哈希/学号/姓名）。

### 12.4 `app/rag_generator.py` —— 答案生成
#### 后端优先级
1. **DeepSeek**：配置 `DEEPSEEK_API_KEY` 时走 HTTPS 对话接口，温度 0.2，最多 500 token；
2. **Ollama**：配置 `OLLAMA_BASE_URL` 时走本地 `/api/chat`；
3. **离线引擎**：无 Key 或前两者失败时兜底，只读链状态，不能编造。

#### 提示词与上下文
- `SYSTEM_PROMPT`：要求只用编号上下文回答，行内引用 `[1][2]`；明确说明有效/撤销/查无此证及块高度；上下文没有答案就明说，不得编造。
- `_numbered_context` / `_chat_messages`：把检索记录编号拼进用户消息。

#### 离线引擎规则链 `_offline(question, records, chain)`
按顺序匹配：
1. 问题中出现精确哈希 → 给该凭证状态行；
2. 问课程 → 列成绩单课程；
3. 凭证记录按姓名/姓/名/学号命中 → 状态行；
4. 8 位学号存在性问题但无匹配 → 告知无记录；
5. 撤销类问题 → 汇总链上撤销条目；
6. 计数类问题 → 统计块数、ISSUE/REVOKE 数、索引凭证数；
7. 签发方/机构问题 → 列注册表名称、算法、指纹前缀；
8. 算法问题 → 报哈希算法与规范化/Merkle 口径；
9. 完整性/篡改问题 → 跑整链校验并报通过/损坏块数；
10. 最新块问题 → 报链尾动作与哈希前缀；
11. 通用：列出前三条相关记录并引导提供具体凭证；
12. 无记录 → 空链提示。

#### 入口 `generate(question, records, chain)`
- 先试 DeepSeek，异常记日志回退；再试 Ollama，异常回退；最后离线引擎；
- LLM 回答时把全部记录列为引用；离线答案带自己的引用编号；
- 返回 `{answer, backend, model, citations}`；`backend_status()` 给人类可读后端描述。

### 12.5 `app/person_context.py` —— 人物上下文与脱敏
- 会话记忆 `_sessions`：`session_id → {person, name}`，上限 200，超限时淘汰最早会话。
- 正则：8 位学号；指代词（he/she/his/her/this person/student/graduate/candidate/applicant 等）；联网意向词（web search / internet / news / public info / background / look up 等）。
- `_raw_documents()`：读链外明文索引；`_verdict(hashed_document)`：调哈希验证取判定与签发高度。
- `_profile(entry)`：组装脱敏档案——姓名、截断学号（前 4 位 + `****`，非 8 位则全遮）、凭证类型、学位、起止、荣誉、机构、部门、签发日、判定、高度、12 位哈希前缀、完整指纹（链上公开标识，供 QR/验证使用）。**DOB 永不进入档案**。
- `resolve_person(question)`：学号精确命中优先；其次姓或全名包含匹配；一人多凭证时优先带学位的文凭条目。
- `remember(session_id, person)`：会话内记住当前人物。
- `context_person(session_id, question)`：问题含指代词时返回记住的人物。
- `wants_web(question, web_flag)`：按钮强制或问题含联网意向词才触发检索。
- `profile_record(person)`：合成一条 RAG 记录，分数钉在 2.0，保证任何生成器都能引用同一脱敏档案而不编事实。

### 12.6 `app/web_research.py` —— 公开信息检索
- 开关：`WEB_RESEARCH_ENABLED` 总开关；`WEB_RESEARCH_MOCK` 演示夹具模式；超时 6 秒。
- 后端：两个免费免密钥公开检索源，依次尝试；任一出结果即返回。
- **隐私硬规则**：查询只含姓名（+ 签发机构）；学号与出生日期绝不进入公开查询。
- 结果标注：公开网络来源单独成卡，注明"不是链上记录"，判定不依赖联网结果；无网络/无结果时返回 `unavailable` 与原因；夹具结果带 `sample/demo` 标记，永不冒充真实来源。

### 12.7 `app/chat_service.py` —— 问答编排
- `MAX_QUESTION_LEN` 500 字符；空问题抛错。
- `_exact_credential_record(question)`：扫明文索引，哈希/学号/姓名精确匹配，返回凭证条目。
- `answer(question, session_id=None, web=False)`：
  1. 截断并校验问题；确保链存在；
  2. 人物解析：先按问题名/学号解析，失败则按会话指代找回；命中后记入会话；
  3. 索引检索 top-6；
  4. 精确命中条目置顶；人物档案记录置顶；把档案指向的同一凭证记录对齐到第二位，保证答案与档案卡哈希/高度一致；
  5. 调生成器；引用为空时兜底列出全部记录编号，保证不会出现零来源答案；
  6. 组装响应：问题、答案、来源、生成后端、模型、人物档案、检索命中数/最高分/嵌入器；
  7. 人物明确要求联网时调 `web_research.search_person(name, org)`；成功在答案末尾附公开来源条数说明（夹具标注），失败说明不可用原因；
  8. 无人物则 `web=None`。
- `rag_status()`：嵌入器、维度、条目数、生成后端、建议问题。
- `_source_view(record)`：来源视图只暴露 id/kind/text/score/高度/动作/哈希等安全字段。

---

## 13. 前端 `static/index.html`

单页、响应式、双语（中文优先英文次级），无前端框架；通过 `fetch` 调上述 API。

- **落地按角色分流**：验证学历 / 我是学生 / 学校管理员；扫码链接 `/verify?hash=...` 直接落到验证页。
- **验证页**：拖拽上传 PDF/JSON、粘贴哈希、样例按钮；判定卡用通俗文案（真实有效 / 已注销 / 查无此证 / 无效 / 链数据损坏）；六检查折叠展开；可下载/打印收据。
- **学生页**：学号 + 出生日期门禁，列出本人凭证，带验证 / 二维码 / 分享链接。
- **管理员页**：批量签发向导（CSV 模板 → 粘贴/上传名单 → 预览好坏行 → 一键签发 → 逐行 PDF/QR）；单条签发；API Key 管理；签发方注册表与激活切换。
- **AI 页**：建议问题 chips、对话气泡、来源引用、脱敏人物卡、联网公开结果卡。
- **日志页**：匿名验证记录、链尾、异常方法徽章与 24 小时直方图、通知流。
- 模式开关：`PUBLIC_MODE=1` 隐藏管理标签并禁用管理端点；`UI_VERIFY_ONLY=1` 前端只留验证、AI、日志三页。

---

## 14. 脚本 `scripts/`

| 脚本 | 作用 |
|---|---|
| `batch_verify.py` | 雇主包 CLI：CSV 输入（含候选哈希列）→ 逐行哈希验证 → CSV 输出（透传原列 + 判定/收据号/汇总行） |
| `backup_chain.py` | 链目录导出/导入单份 tar.gz；可选排除私钥；配合 `CHAIN_SNAPSHOT_URL` 启动恢复 |
| `build_demo_video.py` | 组装演示视频的帧/素材脚本 |
| `live_check.py` | 对运行中实例做存活与关键端点检查 |
| `local_smoke.py` | 两阶段进程内冒烟：公开模式 / 私有模式走通主流程 |
| `run_all_tests.py` | 按测试模块逐个运行，使用隔离链 |

---

## 15. 测试 `tests/`

12 个模块、108 个用例；每条用例建隔离的临时链，互不污染。

| 测试模块 | 用例数 | 覆盖 |
|---|---|---|
| `test_api.py` | 16 | 核心签发/撤销/验证/状态 API |
| `test_custom.py` | 8 | 自助定制生成、落盘、文件解析 |
| `test_employer_pack.py` | 9 | 批量核验、API Key、状态列表、收据登记 |
| `test_extra2.py` | 18 | 文凭 PDF、学生查询、签发方管理、通知、持久化 |
| `test_features.py` | 8 | 二维码、公开日志、异常检测 |
| `test_hardening.py` | 7 | 限流、体积/深度防护、损坏链处理 |
| `test_issue_batch.py` | 5 | 批量签发逐行成败隔离 |
| `test_pdf_extract.py` | 6 | 内嵌载荷提取、文本层字段抽取与置信度 |
| `test_person.py` | 13 | 人物上下文、脱敏、会话指代、联网夹具 |
| `test_public_mode.py` | 6 | 公开验证模式端点 403 与样例凭证 |
| `test_rag.py` | 10 | 索引、检索、离线引擎、引用 |
| `test_restart_persistence.py` | 2 | 重启后链与快照恢复 |

---

## 16. 运行时数据与目录

```
data/
├── demo-chain/
│   ├── info.yaml            # 链元数据 + 签发方注册表
│   ├── blocks/              # 区块 JSON（原子写）
│   ├── rawjsondocs/         # 链外明文凭证索引
│   ├── keys/                # 签发方公钥 PEM；私钥（演示环境）
│   └── active-signer.json   # 当前激活签发方指纹
├── apikeys.json             # API Key 摘要（无明文）
├── receipts.json            # 收据登记表（环形缓冲）
├── public-log.jsonl         # 匿名验证日志
├── notifications.jsonl      # 通知记录（含 dry-run）
└── custom_outputs/          # 自助生成文件回退目录（或 CUSTOM_OUTPUT_DIR）
```

---

## 17. 课程知识映射

| 课程主题 | 对应实现 |
|---|---|
| P3L3 Blockchain | 哈希链区块、创世块、链上/链外数据分离、追加不可改 |
| P2L3 Public Key Cryptography | ML-DSA-65 / RSA-PSS / ECDSA 密钥生成与验签、SPKI 指纹 |
| P2L4 Hash Functions | JCS 规范化、SHA3-512、分段哈希、Merkle 根、base64url 编码 |
| P2L5 Digital Signatures | nonce-HMAC 消息构造、签名/验签流程、签发方注册表 |
| GenAI / RAG | 嵌入向量检索、FAISS、多级生成器回退、来源引用、脱敏与隐私边界 |

---

## 18. 答辩与视频讲稿模板

### 18.1 每人两段式口径
> **功能一句**：我负责 `<模块>`，它解决 `<什么用户问题>`。
> **逻辑一句**：进入模块后先 `<第一步>`，再 `<第二步/核心算法>`，最后 `<输出/判定>`；关键设计是 `<隐私/防篡改/回退/边界>`。

### 18.2 常见提问与回答
- **为什么用链而不是普通数据库？**
  数据库随机构停机/机构关闭可能丢失或被改；哈希链让历史记录互相绑定签名，任何历史篡改都会断掉链接线并被整链校验发现。
- **为什么选 ML-DSA？**
  凭证要保存数十年；传统 RSA/ECC 面临量子计算威胁，ML-DSA 是 FIPS 204 后量子签名算法，同时兼容 RSA-PSS 与 ECDSA 作为过渡。
- **个人隐私怎么保护？**
  链上只存哈希；明文索引在链外；档案卡截断学号、永不含出生日期；联网检索只发姓名+机构；日志只存 12 位哈希前缀；收据不含 DOB 与学号。
- **AI 会不会编造事实？**
  精确 ID 匹配优先于向量检索；离线引擎只读链状态；系统提示词要求只使用编号上下文并引用来源；联网结果单独标注，不参与链上判定。
- **PDF 怎么验证，需要 OCR 吗？**
  门户签发的 PDF 内嵌精确凭证 JSON，提取后走六项密码学检查，不做 OCR；外部扫描件不猜测字段，提示改传 JSON 或手填。
- **这是产品落地了吗？**
  演示规模：JSON 文件存储、内存限流与内存索引；生产应替换为数据库、Redis 限流、KMS/HSM 密钥管理与真实邮件服务。
