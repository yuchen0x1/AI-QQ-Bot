# CHANGELOG

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