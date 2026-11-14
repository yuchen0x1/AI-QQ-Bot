# API

API 前缀为 `/api`，Swagger 为 `/api/docs`，OpenAPI 为 `/api/openapi.json`。除登录、健康检查、Webhook、OneBot 接入外，接口按 JWT + RBAC 保护；JWT 可放 `Authorization: Bearer <token>`，登录也设置 HttpOnly Cookie。

## 认证与用户

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/auth/login` | 登录、签发 JWT；启用 TOTP 时改为返回 5 分钟有效的 `challenge_token` |
| POST | `/auth/login/2fa` | 提交 `challenge_token` + 6 位验证码，换取正式 JWT |
| POST | `/auth/logout` | 撤销当前会话并清除 Cookie |
| GET | `/auth/me` | 当前用户 |
| POST | `/auth/password` | 修改密码；撤销全部旧会话并返回新 JWT |
| GET | `/auth/2fa` | 两步验证状态 |
| POST | `/auth/2fa/setup` | 生成 TOTP 密钥（Fernet 加密存储，返回一次明文密钥与 `otpauth://` URI） |
| POST | `/auth/2fa/confirm` | 提交验证码启用 TOTP |
| POST | `/auth/2fa/disable` | 同时校验密码与验证码后关闭 TOTP，并撤销该用户全部会话 |
| GET | `/auth/sessions` | 当前用户活跃会话（IP、User-Agent、登录/最近使用时间，标记当前会话） |
| DELETE | `/auth/sessions/{id}` | 撤销指定的非当前会话 |
| POST | `/auth/sessions/revoke-others` | 撤销除当前会话外的全部会话 |
| GET/POST/PUT/DELETE | `/users`、`/users/{id}` | 用户管理（重置密码会撤销目标用户全部会话） |
| GET | `/roles`、`/audit-logs` | 角色和审计 |

每个正式 JWT 携带 `jti` 并对应一条 `auth_sessions` 记录；普通 API 与 `/ws/*` 都会校验会话是否被撤销或过期。挑战令牌绑定 `purpose=2fa_challenge`、一次性 nonce 与密码版本，不能重复使用；TOTP 校验带 `totp_last_counter` 防同一时间窗口重放。

## QQ 与群聊

`/accounts` 提供列表、统计、创建/更新/删除、启动/停止/重启、批量动作、能力、连接测试、日志和消息统计；`/groups` 提供列表/详情、群设置、同步群列表/成员、禁言/踢出等动作；`/messages` 提供查询、统计和发送；`/requests` 提供申请分页与审批决定。

创建 / 更新账号时通过 `protocol` 选择接入方式：

| protocol | 必填字段 | 说明 |
|---|---|---|
| `qq_official`（默认） | `app_id`、`app_secret` | QQ 官方机器人开放平台；`connection_mode` 固定为 `official_ws` |
| `onebot11` | `api_base`；`ws_client` 模式还需 `ws_url` | 旧版 NapCat / Lagrange 兼容通道 |
| `mock` | 无 | 仅本地测试 |

官方账号可选字段：`official_sandbox`（沙箱环境）、`official_intents`（事件订阅位值，默认 `33554432` = `1<<25`）、`official_allow_proactive`（允许主动消息，默认 true）、`official_api_base`（覆盖 OpenAPI 域名）。`app_secret` 与 `access_token` 均加密存储，接口只回显 `has_secret` / `has_token`；编辑时传空字符串表示保持不变。

`GET /accounts/{id}/capabilities` 会按协议返回真实能力；官方平台不支持禁言、踢人、改群名/公告/名片、设管理员、撤回、审批申请与全量列表查询。`POST /accounts/{id}/test-connection` 对官方账号只校验凭据与 `/gateway` 可达性，不占用长连接会话额度。

OneBot v11 协议端点（仅旧接入使用，官方机器人由 backend 主动连接平台 Gateway，无需下列回调）：

- `POST /onebot/v11/events/{account_uid}`：HTTP 事件上报。
- `WS /onebot/v11/ws/{account_uid}`：反向 WebSocket 事件流。
- 两者均使用 query `access_token` 或 Bearer token 做 fail-closed 校验；账号未配置 token 时拒绝接入。

QQ 官方机器人 Webhook 回调（免登录态，由 Ed25519 签名保护）：

- `POST /qqbot/webhook/{app_id}`：推荐形式，按路径 AppID 定位账号；也可用 `POST /qqbot/webhook` 携带 `X-Bot-Appid` 请求头；Nginx 另提供 `POST /webhook` 兼容转发。
- `op=13` 地址验证：读取 `d.plain_token` / `d.event_ts`，用账号 AppSecret 派生的 Ed25519 私钥签 `event_ts + plain_token`，返回 `{"plain_token", "signature"}`；无需账号在线。
- `op=0` 事件推送：校验 `X-Signature-Ed25519`（hex）与 `X-Signature-Timestamp`（签名体 = timestamp 原文 + 原始 body，默认 300 秒时间窗，`QQBOT_WEBHOOK_MAX_AGE_SECONDS` 可调，0 关闭时间校验），通过后注入在线账号的事件队列；账号离线或接入模式不匹配返回 503 交由平台重试；验签失败返回 401 并写账号日志（含 `X-Tps-Trace-Id`）。

## AI、GitHub、任务和插件

- `/ai/presets`、`/ai/providers`、`/ai/models`、`/ai/chat`、`/ai/conversations`、`/ai/usage`：Provider/模型/会话/用量。`POST /ai/providers/{id}/sync-models` 拉取供应商模型列表（OpenAI 兼容 `/models`、Anthropic、Gemini、Ollama 各自适配）并把缺失的对话模型补进已配置列表——去重、过滤向量/TTS/语音等非对话模型、上限 100 个，不删除或修改已有模型；供应商保存后管理台会自动触发一次。
- `/github/repos`、`/github/push-rules`、`/github/push-records`：仓库、规则、记录和重试；仓库 provider 当前支持 GitHub 与 Gitee。
- `POST /webhook/github/{repo_id}`：GitHub Release Webhook。当前实现对所有环境统一要求 Secret；仓库未配置 Secret 时返回 **409**，配置 Secret 后必须校验 `X-Hub-Signature-256`，签名错误返回 **401**，通过后按 delivery/release 去重。开发/测试若需覆盖无密钥路径，应使用专门测试替身，不应放行真实端点。
- `/tasks`、`/tasks/records`：任务定义、立即执行、切换和执行记录。
- `/plugins`：同步、重载、启用状态和账号/群绑定。

## GitHub OAuth 授权

让网页用户绑定自己的 GitHub 账号，替代手工粘贴 Personal Access Token；Token 只加密存储于服务端，任何接口都不回显明文。

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/github/oauth/status` | `github:view` | 是否已配置 OAuth App、当前用户是否已绑定、授权范围、回调地址 |
| GET | `/github/oauth/start?next=/github` | `github:manage` | 浏览器整页跳转入口，302 到 GitHub 授权页 |
| GET | `/github/oauth/callback` | 免登录（`state` 签名保护） | GitHub 回调：校验签名 state → code 换 Token → 写入绑定；成功后 302 回 `next?github=connected`，失败 302 回 `?github=error&reason=...` |
| POST | `/github/oauth/disconnect` | `github:manage` | 解除当前用户的绑定（已监控仓库保留） |
| GET | `/github/oauth/repos?page=1` | `github:manage` | 拉取授权账号的仓库列表（含私有），标注 `monitored` |
| POST | `/github/oauth/import` | `github:manage` | 批量导入 `{"full_names":["owner/repo"],"poll_interval_seconds":900}`，单次最多 30 个 |
| GET/PUT | `/github/oauth/app` | `system:manage` | 读取/保存 OAuth App 的 Client ID、Client Secret（加密）、Scopes |

要点：

- `state` 是 10 分钟有效的签名 JWT，内含平台用户 ID 与 `next` 跳转路径；`next` 只允许站内相对路径，防开放重定向。回调不依赖登录 Cookie，完全靠签名校验身份。
- OAuth App 凭据的解析顺序是「数据库 `system_settings.github_oauth` → 环境变量 `GITHUB_OAUTH_CLIENT_ID/SECRET`」，因此可以在网页端配置而无需重启。
- 仓库取用凭据的顺序是「仓库自带 PAT → 归属用户绑定的 OAuth Token → 全局 `GITHUB_TOKEN`」。OAuth 导入的仓库**不复制** Token，用户重新授权或解绑后立即生效。
- 仓库按 `owner_user_id` 隔离：普通用户只能看到自己添加的仓库与历史全局仓库（`owner_user_id` 为空），超级管理员不受限；越权访问返回 403，列表过滤不泄露他人仓库。
- 仓库检查、推送规则、推送记录同样套用归属过滤，避免通过规则/记录绕过隔离。

## 系统与实时通道

- `/system/health`：健康检查；`/system/stats`、`/system/info`、`/system/settings`、`/system/backups`、`POST /system/backup`。
- `/logs`：日志分类、分页和清理。
- `WS /ws/status`：账号/任务/消息状态；`WS /ws/logs`：日志流；`WS /ws/events`：统一 `type/id/time/data` 事件流，支持 `account_id` 过滤。

统一错误通常使用 `{"detail":"..."}`；能力不支持、账号离线、权限不足和凭据错误分别返回明确的 4xx。具体请求/响应 schema 以 Swagger 和 `backend/app/schemas` 为准。