# ARCHITECTURE

## 总体结构

```text
浏览器(Vue 3 + Element Plus)
        │ /api、/ws
Nginx(SPA + 反向代理)
        │
FastAPI backend ── SQLAlchemy Async ── PostgreSQL(生产)/SQLite(本地测试)
        ├─ AccountManager ── QQOfficialAdapter（默认，bot.qq.com Gateway）
        ├─ QQIdentityService ── qq_official_identities（OpenID ↔ 整数 ID）
        ├─ BotEngine：消息、命令、审核、审计、AI、插件钩子
        ├─ AI Provider：OpenAI 兼容、Anthropic、Gemini、Ollama
        ├─ Repository Monitor：GitHub/Gitee 轮询、GitHub Webhook、Release、去重、QQ 推送
        ├─ SchedulerService：APScheduler、任务记录、重试
        └─ EventHub：进程内事件广播、日志/状态 WebSocket
Redis(Compose 默认启用，队列能力预留)
```

QQ 官方机器人支持两种事件接入，账号表单「回调方式」决定：**WebSocket 模式**由 backend 主动外连：AppID + AppSecret → `POST https://bots.qq.com/app/getAppAccessToken` → `GET /gateway` → WebSocket 连接 → OpCode 10 Hello → OpCode 2 Identify（Intents `1<<25`）→ READY → 应用层心跳（OpCode 1/11）。断线优先发 OpCode 6 Resume 恢复会话，收到 OpCode 7/9 则重新 Identify。**Webhook 模式**不建长连接：`POST /api/qqbot/webhook/{app_id}`（另有 `X-Bot-Appid` 头路由与 Nginx `=/webhook` 兼容转发）先处理 `op=13` 地址验证（AppSecret 派生 Ed25519 seed，签 `event_ts+plain_token` 返回），再对 `op=0` 事件用公钥验签 `timestamp+原始body`（默认 300 秒时间窗），通过后 `feed_event` 注入与 WebSocket 完全相同的事件队列，账号未在线返回 503 交由平台重试。事件主要为 `GROUP_AT_MESSAGE_CREATE`、`C2C_MESSAGE_CREATE`、`GROUP_ADD_ROBOT/DEL_ROBOT`、`FRIEND_ADD/DEL`。

## 后端边界

- `app/main.py`：生命周期、生产安全校验、CORS、安全响应头、限流和异常处理。
- `app/api/`：认证、账号、群组、申请、消息、AI、GitHub（含 OAuth 授权）、任务、插件、日志、系统、Webhook、WebSocket 路由。
- `app/services/account_manager.py`：每个账号独立运行时和适配器；`build_adapter()` 仅创建 QQ 官方适配器，其他协议明确拒绝；负责连接状态、指数退避、跨进程数据库租约。
- `app/adapters/base.py`：`QQAdapter` 抽象接口与 `CAPABILITIES` 能力表。业务核心只依赖这个边界。
- `app/adapters/qq_official.py`：官方平台接入。AccessToken 缓存与刷新、Gateway 状态机、事件解析、OpenID 映射、被动回复窗口、主动消息降级、平台错误码翻译。
- `app/services/qq_identity.py` + `app/models/account.py::QQOfficialIdentity`：把字符串 OpenID 映射为稳定整数 ID，按账号隔离，`member` 类型带 `scope`（所属群 OpenID）。
- `app/services/bot_engine.py`：事件落库后按自动管理 → 命令 → AI → 插件钩子处理；不感知底层协议。
- `app/services/scheduler.py`：随 backend 进程启动（与机器人连接同进程），任务执行直接调用共享业务服务；发送类任务不能投递给 worker。
- `app/core/events.py`：进程内事件信封为 `type/id/time/data`，当前不提供跨进程广播。
- `app/services/github/oauth.py`：GitHub OAuth 授权。`state` 是 10 分钟有效、带用途声明的签名 JWT（含平台用户 ID 与站内 `next`），无需落库即可跨副本校验；code 换 Token、拉取账号信息与仓库列表；Token 用 Fernet 加密后写入 `user_github_tokens`，接口只回显登录名与授权范围。OAuth App 凭据优先读 `system_settings.github_oauth`，其次读环境变量。
- `app/services/github/registry.py`：仓库创建的唯一入口（网页手动添加与 OAuth 批量导入共用），负责仓库可访问性校验、历史 Release 导入（标记已通知）和轮询任务注册；同时提供 `owner_user_id` 归属判定，普通用户只能看到自己的仓库与历史全局仓库。
- `app/services/github/monitor.py`：`resolve_repo_token()` 决定调用凭据——仓库自带 PAT → 归属用户绑定的 OAuth Token → 全局 `GITHUB_TOKEN`，因此 OAuth 导入的仓库不复制凭据，重新授权/解绑后下一轮轮询即生效。

## 进程与部署模式

Compose 服务为 `postgres`、`redis`、`backend`、`frontend`、`nginx`（backend 内置调度器）；`worker` 需显式启用 `--profile workers`，已具备 Redis 队列消费者：仅当 `REDIS_ENABLED=true` 且 `REDIS_QUEUE_ENABLED=true`、外部 Redis 可用时消费，且只接收 `CONNECTION_BOUND_TASKS` 之外的任务，真实部署尚未验收。测试替身仅位于 tests 中，通过测试夹具注入，不进入生产运行镜像。

## 关键数据流

1. 官方机器人事件由 Gateway WebSocket 推送或 Webhook 端点验签后注入 `QQOfficialAdapter`，统一转换为 `AdapterEvent`（OpenID 已映射为整数 ID）。
2. AccountManager 将事件交给 BotEngine；消息、群成员、申请和操作结果写入数据库。
3. BotEngine 回复时调用 `adapter.send_group_message/send_private_message`：官方适配器优先复用入站事件的 `msg_id` + 递增 `msg_seq` 走被动消息；窗口过期 / 次数用尽后按账号配置降级为主动消息。
4. GitHub Webhook 先做 HMAC-SHA256 验签，再按 delivery/release 去重；轮询由 APScheduler 触发。定时推送 / GitHub 通知没有入站事件，直接走主动消息，受平台频控约束。
5. 前端通过 REST 获取页面数据，通过 `/api/ws/status`、`/api/ws/logs` 或 `/api/ws/events` 获取实时状态/日志。

## 扩展边界

`QQAdapter` 是唯一协议适配边界；不支持的动作通过能力检测返回明确错误，绝不假装成功。官方平台缺少的能力（群管理、申请审批、全量列表、撤回）在能力页标记为不支持；自动审核中的 mute/kick 会降级为记录日志。插件通过清单声明权限和按账号/群绑定，但动态 Python 插件仍必须在受信环境运行。水平扩展前需将连接管理与 EventHub 迁移到独立连接服务和共享事件/租约机制。GitHub OAuth 的 `state` 用 `SECRET_KEY` 签名，多副本部署天然一致；`user_github_tokens` 的 Token 轮换由用户重新授权完成，不需要额外的刷新任务。
