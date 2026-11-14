# CHANGELOG

## 2026-11-14 — 新手指引六步升级（v1.4.5）

- **向导新增「配置 AI 模型」步骤**（index 1）：ready = 存在启用的 AI 供应商且至少一个启用模型（join 查询）；`GuideProgress.step` 上限 le=4→le=5；课程覆盖自动获取模型、默认/备用/优先级、沙盒试聊与 AI 摘要路由。
- **操作文档 +3 篇**：Markdown 卡片（默认开启/权限/降级）、归档仓库自动移除、AI 自动获取模型；「验证群通知」课程 note 补卡片默认开启说明；App.vue 首次使用弹窗文案同步。
- **去硬编码**：HelpView 步骤上限改 `setupLessons.length - 1`，「可稍后设置」改读后端 optional 字段，QQ 授权实图改按课程 `illustrations` 标记渲染。
- 验证：新增 onboarding AI 步骤就绪测试、迁移 steps 数量断言 5→6；后端全量 pytest 通过（229 项）、Ruff 通过、前端构建通过；`prepare_release.py --tag v1.4.5` 校验通过。

## 2026-11-14 — AI 供应商自动获取模型（v1.4.4）

- **自动导入**：`providers.py` 各供应商类新增 `list_models()`（OpenAI 兼容 `_models_endpoint` 兼容 /v1、/compatible-mode/v1 与完整 chat 端点写法）；`api/ai.py` 新增 `POST /providers/{id}/sync-models`——拉取、去重、过滤非对话模型（embed/tts/whisper/speech/dall-e/moderation/rerank/guard）、上限 100、跳过已存在（provider_id+model_name 唯一约束兜底），只新增不删改。
- **前端**：供应商保存后自动触发拉取并提示导入数量；卡片新增「获取模型」按钮（带 loading），失败提示原因可重试。
- 验证：新增 2 项测试（拉取过滤+去重+默认参数、不可达供应商明确报错）；后端全量 pytest 通过、Ruff 通过、前端构建通过；`prepare_release.py --tag v1.4.4` 校验通过。

## 2026-11-14 — 归档卡片崩溃修复与卡片默认开启（v1.4.3）

- **崩溃修复**：`normalize_activity` 的 create/delete（创建/删除分支或标签）分支漏赋 `card`，仓库出现此类事件后每轮检查都抛 `UnboundLocalError` 并触发告警邮件（生产 PROJECT-NEXUS 每 5 分钟一次）。补上活动卡片数据，积压事件升级后自动消化。
- **卡片默认开启**：模型默认值改 `True`；迁移 `0013_markdown_card_default_on` 将存量 107 条规则全部翻开；`reconcile_rules` 自动建规则带 `markdown_card=True`；新建规则的 API 与前端表单默认开启。此前生产从未真正发过卡片（全库规则无一开启，纯文本投递）。降级保护不变：无 Markdown 权限或发送被拒自动回退纯文本。
- 验证：新增 2 项回归测试（create/delete 事件卡片投递、新建规则默认开卡片）；后端全量 pytest 通过、Ruff 通过；`prepare_release.py --tag v1.4.3` 校验通过。

## 2026-11-14 — 归档仓库自动移除与 SQLite 外键修复（v1.4.2）

- **归档自动移除**：`monitor.py` 新增 `remove_archived_repository`——轮询 `check_repository`（`get_repo` 的 `archived` 字段，零额外请求）与 Webhook `repository/archived` 事件都会触发：先向绑定的启用通知群（按账号+群去重）尽力发送告知消息，再取消调度、删除仓库行（级联版本/规则/事件/推送记录）、写系统日志；通知失败不阻塞移除。
- **防回流**：OAuth 全量同步（`sync_subscription`）跳过 `archived` 仓库，删除后不会被重新导入；`create_monitored_repo` 拒绝添加归档仓库（API 返回 400 与原因）。仓库删除/转移仍按既有「不可访问」语义保留历史。
- **SQLite 外键修复**：`app/db/session.py` 连接事件显式执行 `PRAGMA foreign_keys=ON`——此前 31 个外键的 `ondelete=CASCADE/SET NULL` 在 SQLite（含原生部署）从未生效，删除父记录会残留孤儿行；现在与 PostgreSQL 一致。测试同步修正两处引用不存在父记录的种子数据（retention / card），新增 4 项测试覆盖轮询移除+群通知、Webhook 移除、添加拒绝、同步防回流。
- 验证：后端全量 pytest 通过（224 项，exit 0）、Ruff 通过；`prepare_release.py --tag v1.4.2` 校验通过。

## 2026-11-14 — 升级服务国内镜像加速（v1.4.1）

- **下载镜像**：原生升级服务 `/etc/qbot/updater.json` 新增 `download_mirrors`——升级包按 gh-proxy 风格前缀镜像逐源下载（每源独立 300s 超时），全部失败自动回退 GitHub 直连；镜像仅作传输通道，SHA-256 digest 仍以直连 `api.github.com` 的元数据为锚，重定向白名单扩展为「镜像主机 ∪ GitHub 主机」，非法镜像条目启动时被忽略。
- **pip 镜像**：新增 `pip_index_url`，依赖安装（`build_environment.py`）按该 PyPI 镜像源执行；镜像校验同 allowed_url 规则（HTTPS、无凭据）。
- **元数据重试**：`fetch_release` 对 URLError/超时/连接重置自动重试一次，HTTP 4xx/5xx 等确定性错误不重试。
- **部署提示**：宿主机升级服务代码不随网页升级更新，需管理员将 `scripts/updater/daemon.py`、`build_environment.py` 复制到 `/usr/local/lib/qbot-updater/` 并重启 `qbot-updater` 后配置生效（见 `docs/AUTO_UPDATE.md` 国内服务器加速章节）。
- 验证：新增 `tests/test_self_update.py` 8 项（镜像 URL 构造/非法条目过滤、镜像失败回退直连、digest 不匹配换源、重定向白名单、元数据重试与 HTTP 错误不重试）；后端全量 pytest 通过、Ruff 通过（含 scripts/updater）。

## 2026-11-14 — GitHub 通知官方 Markdown 卡片（v1.4.0）

- **卡片渲染**：新增 `app/services/github/card.py`——代码推送渲染标题 / 分支 / 提交内容 / 变化文件 / 行数统计 / 提交信息的官方原生 Markdown 深色卡片（msg_type=2）+ keyboard 跳转按钮；Issue、PR、Star 等动态走通用卡片；版本发布通知经 `render_release_message` 双产出（纯文本 + 卡片数据）。
- **开关与持久化**：`push_rules.markdown_card` 逐规则开关（默认关闭）；发布卡片数据存 `push_records.card_payload`（迁移 `0012_push_rule_markdown_card`），重试 / 手动重发仍以卡片投递；动态事件按 `event_id` 现场渲染。
- **硬性降级**：`send_push_record` 统一投递入口——卡片渲染失败、机器人无 Markdown / 按钮权限、接口拒绝时自动降级纯文本重发并记 WARNING 日志，推送永不中断；旧记录无卡片数据自动回退纯文本。
- **一致性**：规则的「AI 摘要 / 附带更新日志 / 附带下载地址」开关同样作用于卡片；消息模板仅影响纯文本版；轮询路径复用 compare 响应补充行数统计（`payload._compare`）。
- 验证：`tests/test_github_card.py` 11 项（渲染结构 / keyboard 约束 / 围栏中和 / 降级路径 / 重试发卡）；后端全量 pytest 通过、Ruff 通过、前端构建通过。

## 2026-11-08 — 后台两步验证与登录会话管理

- **TOTP 两步验证**：新增 `app/core/totp.py`（标准库实现，Base32 密钥、HMAC-SHA1、6 位 / 30 秒、前后各容忍 1 个时间窗、`otpauth://` URI），无新增第三方依赖。`users` 增加 `totp_secret_enc`（Fernet 加密）、`totp_enabled`、`totp_last_counter`（防同一时间窗重放）、`totp_challenge_nonce`。
- **登录流程**：启用 2FA 后 `POST /auth/login` 不再直接发正式令牌，改为返回 5 分钟有效的 `challenge_token`（绑定 `purpose=2fa_challenge`、一次性 nonce 与密码版本）；`POST /auth/login/2fa` 校验挑战、TOTP 与限流后签发正式 JWT。前端登录页新增验证码阶段（`autocomplete="one-time-code"`）。
- **2FA 管理 API**：`GET /auth/2fa`、`POST /auth/2fa/setup|confirm|disable`。setup 只在未启用时生成密钥；confirm 必须提交当前验证码；disable 同时校验密码与验证码，成功后撤销该用户全部会话。设置页新增绑定向导（二维码、手动密钥复制、启用/关闭）。
- **登录会话**：`create_access_token` 默认携带 `jti`，新表 `auth_sessions`（迁移 `0006_auth_security`）记录 IP、User-Agent、过期与最近访问时间。`get_current_user` 与三个 WebSocket 端点均校验会话存在、未撤销、未过期；退出登录、改密、管理员重置密码都会撤销对应会话，改密接口返回新 JWT 供前端平滑续接。
- **会话 API**：`GET /auth/sessions`、`DELETE /auth/sessions/{id}`（禁止撤销当前会话）、`POST /auth/sessions/revoke-others`；设置页新增活跃会话列表（设备、IP、登录/最近使用时间、当前标记、撤销操作）。
- 兼容性：不带 `jti` 的历史 JWT 仍按原密码版本机制校验，升级后旧令牌不会突然全部失效，新签发令牌才进入数据库会话校验。
- 验证：后端 pytest 97 项通过（含 TOTP 登录、挑战重放拒绝、验证码重放、会话撤销、迁移 head 一致性）；`ruff check app tests migrations` 通过；`npm run build` 通过。

## 2026-11-05 — 运行时稳定性修复（P0）

- **AI 回复移出事件流**：`BotEngine` 新增后台任务调度（`schedule_ai_reply`），消息落库、自动管理、命令响应仍在事件流内同步完成，只有 AI 生成被移到独立任务。按账号的 `asyncio.Semaphore`（`AI_MAX_CONCURRENCY`，默认 4）限制在途请求，按 `(账号, 群/私聊)` 的会话锁保证同一会话内顺序不被打乱。修复了「一条慢模型请求让同账号所有群消息排队，队列打满后阻塞 WebSocket reader」的吞吐瓶颈。
- **修复 `/ai` 命令永不触发 AI**：`commands.dispatch` 末尾原为 `return result or None`，把表示「交给引擎生成」的空字符串吞成了 `None`，导致群内 `/ai 问题` 只被当成未命中命令。改为原样返回，空串语义恢复。
- **限流器 key 回收**：`SlidingWindowLimiter` 与自动管理的 `RateTracker` 增加有上限的过期清扫（每 1000 次调用触发，单次最多 500 个 key），消除公网扫描/大量用户导致的字典单调增长。
- **旧版回调限流**：根路径 `/webhook` 不在 `/api` 前缀下，原先完全绕过限流；新增 `legacy_webhook_limiter`（120 次/分钟/IP）。同时把回调路径匹配改为按路径段判断，避免 `/api/webhook-foo` 被误豁免。
- 测试新增 `tests/test_runtime_safety.py` 6 项（后台化不阻塞、同群串行、跨群并发、限流清扫、旧回调限流、路径边界），全量 92 项通过；`ruff check app tests migrations` 通过。

## 2026-11-05 — GitHub OAuth 授权与仓库归属隔离

- 新增 `app/services/github/oauth.py`：`state` 使用 10 分钟有效的签名 JWT（含平台用户 ID 与站内 `next`，拒绝 `//` 与反斜杠以防开放重定向）；`code` 换 Token（同时兼容 JSON 与表单响应）、拉取账号信息、分页列出授权账号的仓库；Token 以 Fernet 加密写入 `user_github_tokens`，接口只回显登录名 / 头像 / 授权范围。
- 新增 `app/api/github_oauth.py`：`GET /api/github/oauth/status|start|callback|repos`、`POST /api/github/oauth/disconnect|import`、`GET/PUT /api/github/oauth/app`。回调不依赖登录 Cookie，完全由签名 `state` 确定身份；成功后 302 回前端并带 `github=connected`，失败带 `error` + 原因。
- 新增 `app/services/github/registry.py`：把仓库创建收敛为唯一入口（网页手动添加与 OAuth 导入共用），统一处理可访问性校验、历史 Release 导入与轮询注册；同时提供 `owner_user_id` 归属判定。
- 新增迁移 `0005_github_oauth`：创建 `user_github_tokens`（`user_id` / `github_id` 双唯一），为 `github_repositories` 增加 `owner_user_id` 与索引；SQLite 不支持为已有表追加外键，该列按软引用处理，删除用户时由 API 置空，`alembic check` 保持零差异。
- 凭据取用改为三级回退：仓库自带 PAT → 归属用户绑定的 OAuth Token → 全局 `GITHUB_TOKEN`。OAuth 导入的仓库不复制 Token（`persist_token=False`），用户重新授权或解绑后下一轮轮询立即生效，避免两份凭据漂移。
- 仓库隔离：普通用户仅能看到自己添加的仓库与历史全局仓库（`owner_user_id` 为空），超级管理员不受限；仓库详情、检查、Webhook 信息、密钥重置、推送规则与推送记录同样套用归属校验，越权返回 403。
- OAuth App 凭据支持网页配置：`system_settings.github_oauth` 优先，环境变量 `GITHUB_OAUTH_CLIENT_ID/SECRET` 兜底；前端只拿到打码后的 Client ID，留空表示保持不变，避免把掩码写回。
- 前端 GitHub 页新增绑定状态卡片（绑定 / 解绑 / 重新授权）、仓库导入对话框（搜索、私有标记、已监控不可选、轮询间隔与预发布开关）、OAuth App 配置对话框（含创建步骤与一键复制回调地址），并处理回调后的成功 / 失败提示。
- 测试新增 6 项（配置前状态、完整授权与导入、伪造 state、Token 交换失败、跨用户隔离、解绑保留仓库），全量 85 项通过；`ruff check app tests migrations` 通过；`npm run build` 通过。
- 文档更新：README / API / ARCHITECTURE / DATABASE / `.env.example`；顺带修正 ARCHITECTURE 中「官方 Webhook 模式未实现」的过期描述。

## 2026-11-05 — 官方机器人新增 Webhook 回调方式

- 新增 `app/services/qq_webhook_crypto.py`：按官方规则把 AppSecret repeat 扩展为 32 字节 Ed25519 seed；`op=13` 回调地址验证签名与 `op=0` 事件验签均与官方文档 DEMO 逐字节对齐（含公钥与签名常量测试）。
- 新增 `app/api/qqbot_webhook.py`：`POST /api/qqbot/webhook/{app_id}`（支持 `X-Bot-Appid` 头路由与 Nginx `=/webhook` 兼容转发），处理 op=13 握手（账号无需在线）、op=0 事件验签（默认 300 秒时间窗）后注入在线适配器；离线 / 模式不匹配返回 503 由平台重试，验签失败写账号日志并携带 `X-Tps-Trace-Id`。
- `QQOfficialAdapter` 新增 `callback_mode`：Webhook 模式启动零网络依赖（AccessToken 按需获取），事件与心跳复用同一队列，`probe()` 按模式区分探测内容。
- 账号 `connection_mode` 支持 `official_ws` / `official_webhook`，前端表单可选回调方式并回显完整回调地址；跨协议切换时自动规范化接入模式；平台回调端点不受 API 限流约束。
- 测试新增 12 项（官方签名样例、验签篡改拒绝、握手、事件注入与去重、启动无网络依赖、模式切换规范化），全量 79 项通过。

## 2026-11-04 — 接入方式切换为 QQ 开放平台官方机器人

- 新增 `qq_official` 协议：AppID + AppSecret 换取 AppAccessToken，主动连接官方 Gateway WebSocket，实现 Hello/Identify/Heartbeat/Resume/Reconnect/InvalidSession 状态机、应用层心跳与会话恢复。不再扫码登录个人 QQ 号，规避登录风控。
- 新增 `app/adapters/qq_official.py`：平台事件解析（`GROUP_AT_MESSAGE_CREATE` / `C2C_MESSAGE_CREATE` / `GROUP_ADD_ROBOT` 等）、被动回复窗口（5 分钟、群 5 次 / 单聊 4 次、`msg_seq` 递增）、过期自动降级主动消息、平台 `err_code` 中文排查提示、AccessToken 缓存与过期刷新、401 强制刷新重试。
- 新增 `app/services/qq_identity.py` 与 `qq_official_identities` 表（`0004_qq_official` 迁移）：把 `group_openid` / `user_openid` / `member_openid` 稳定映射为内部整数 ID，使 BotEngine、群聊、AI 会话、消息统计等上层模块保持零改动。
- 账号模型/Schema/API 增加 `app_id`、加密的 `app_secret_enc`、`bot_openid` 及 `official_sandbox` / `official_intents` / `official_allow_proactive` / `official_api_base` 配置；修复编辑账号时空密钥会清空凭据的问题；`build_adapter()` 按协议路由；官方连接错误给出平台专属提示。
- 能力集按官方平台真实能力裁剪：禁言、踢人、改群名/公告/名片、设管理员、撤回、申请审批、全量好友/群/成员列表均明确标记为不支持；自动审核中的 mute/kick 降级为记录日志，不假装成功。
- 前端账号页主入口改为「添加机器人」，表单按协议动态显示字段；NapCat 扫码降级为「NapCat 扫码（旧版）」兼容入口，OneBot v11 高级接入保留。
- 文档与配置更新：README / ARCHITECTURE / API / `.env.example` / docker-compose，说明开放平台配置步骤、能力差异、频控与排障。
- 当前验证：后端 `pytest` 66 passed（含新增 12 个官方机器人单测与 `alembic check` 一致性检查）；`ruff check app tests migrations` 通过；`npm run build` 通过（vue-tsc + Vite，2326 modules）。真实平台联调需提供 AppID / AppSecret 与已认证的开放平台机器人。

## 2026-11-03 — 数据库 schema 改为 Alembic 单一真相

- 启动初始化拆分为两步：先 `alembic upgrade head`，再执行幂等种子数据（角色/管理员/设置/命令/插件）；移除启动时 `Base.metadata.create_all`。
- `0001_initial` 改为显式 DDL 快照；`0002`、`0003` 保持对旧库的幂等兼容，并补齐 `lease_id` 唯一索引。
- 新增 `SchemaVersionError`：旧库缺少 `alembic_version` 或版本不在迁移链中时拒绝启动并给出处理指引，不静默建表。
- 新增迁移测试：空库升级、重复升级、种子幂等、版本落后升级、未知版本/未纳管旧库拒绝。
- 当前验证：后端 pytest 50 passed；ruff 通过；`alembic check` 确认迁移 schema 与模型一致。

## 2026-11-03 — 当前审计基线

### 已交付

- FastAPI 异步 API、Vue 3/TypeScript 控制台和 Element Plus 页面。
- 多账号 OneBot v11/Mock 适配、群聊/成员/消息/申请审核和 BotEngine。
- JWT、bcrypt、RBAC、登录失败锁定、限流、审计日志和敏感字段 Fernet 加密。
- AI Provider/模型/会话/用量/fallback。
- GitHub/Gitee 仓库与 Release 轮询、GitHub Webhook 验签、去重、规则、推送历史和失败重试。
- APScheduler 任务、任务记录、备份脚本、插件发现/加载/绑定。
- Docker Compose：PostgreSQL、Redis、backend、scheduler、frontend、nginx，NapCat/worker profile；Worker 已具备可选 Redis 队列消费者。
- Alembic `0001_initial`、`0002_bot_requests`；当前工作树还包含 `0003_runtime_leases`，增加账号运行租约和任务队列元数据。
- 当前代码改造加入生产安全配置校验、跨进程账号租约、统一进程内事件信封和 `/api/ws/events`。

### 当前验证

- 后端 pytest：43 passed。
- Ruff：通过。
- 前端构建：后续复测已通过 `vue-tsc -b` 和 Vite 生产构建（2326 modules transformed）。

### 未承诺为完成

Redis 队列 worker、水平扩展连接服务、跨实例事件/限流、真实 NapCat/GitHub/AI 集成、TLS/监控告警、生产恢复演练仍需目标环境验收。