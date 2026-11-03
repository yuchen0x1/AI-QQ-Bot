# API

API 前缀为 `/api`，Swagger 为 `/api/docs`，OpenAPI 为 `/api/openapi.json`。除登录、健康检查、Webhook、OneBot 接入外，接口按 JWT + RBAC 保护；JWT 可放 `Authorization: Bearer <token>`，登录也设置 HttpOnly Cookie。

## 认证与用户

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/auth/login` | 登录、签发 JWT |
| POST | `/auth/logout` | 清除 Cookie |
| GET | `/auth/me` | 当前用户 |
| POST | `/auth/password` | 修改密码 |
| GET/POST/PUT/DELETE | `/users`、`/users/{id}` | 用户管理 |
| GET | `/roles`、`/audit-logs` | 角色和审计 |

## QQ 与群聊

`/accounts` 提供列表、统计、创建/更新/删除、启动/停止/重启、批量动作、能力、连接测试、日志和消息统计；`/groups` 提供列表/详情、群设置、同步群列表/成员、禁言/踢出等动作；`/messages` 提供查询、统计和发送；`/requests` 提供申请分页与审批决定。

OneBot v11 协议端点：

- `POST /onebot/v11/events/{account_uid}`：HTTP 事件上报。
- `WS /onebot/v11/ws/{account_uid}`：反向 WebSocket 事件流。
- 两者均支持 query `access_token` 或 Bearer token，账号未配置 token 时当前实现允许空 token，生产应配置令牌。

## AI、GitHub、任务和插件

- `/ai/presets`、`/ai/providers`、`/ai/models`、`/ai/chat`、`/ai/conversations`、`/ai/usage`：Provider/模型/会话/用量。
- `/github/repos`、`/github/push-rules`、`/github/push-records`：仓库、规则、记录和重试；仓库 provider 当前支持 GitHub 与 Gitee。
- `POST /webhook/github/{repo_id}`：GitHub Release Webhook。当前实现对所有环境统一要求 Secret；仓库未配置 Secret 时返回 **409**，配置 Secret 后必须校验 `X-Hub-Signature-256`，签名错误返回 **401**，通过后按 delivery/release 去重。开发/测试若需覆盖无密钥路径，应使用专门测试替身，不应放行真实端点。
- `/tasks`、`/tasks/records`：任务定义、立即执行、切换和执行记录。
- `/plugins`：同步、重载、启用状态和账号/群绑定。

## 系统与实时通道

- `/system/health`：健康检查；`/system/stats`、`/system/info`、`/system/settings`、`/system/backups`、`POST /system/backup`。
- `/logs`：日志分类、分页和清理。
- `WS /ws/status`：账号/任务/消息状态；`WS /ws/logs`：日志流；`WS /ws/events`：统一 `type/id/time/data` 事件流，支持 `account_id` 过滤。

统一错误通常使用 `{"detail":"..."}`；能力不支持、账号离线、权限不足和凭据错误分别返回明确的 4xx。具体请求/响应 schema 以 Swagger 和 `backend/app/schemas` 为准。