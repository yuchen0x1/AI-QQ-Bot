# ARCHITECTURE

## 总体结构

```text
浏览器(Vue 3 + Element Plus)
        │ /api、/ws
Nginx(SPA + 反向代理)
        │
FastAPI backend ── SQLAlchemy Async ── PostgreSQL(生产)/SQLite(本地测试)
        ├─ AccountManager ── OneBot11/NapCat 或 Mock Adapter
        ├─ BotEngine：消息、命令、审核、审计、AI、插件钩子
        ├─ AI Provider：OpenAI 兼容、Anthropic、Gemini、Ollama
        ├─ Repository Monitor：GitHub/Gitee 轮询、GitHub Webhook、Release、去重、QQ 推送
        ├─ SchedulerService：APScheduler、任务记录、重试
        └─ EventHub：进程内事件广播、日志/状态 WebSocket
Redis(Compose 默认启用，队列能力预留)
```

## 后端边界

- `app/main.py`：生命周期、生产安全校验、CORS、安全响应头、限流和异常处理。
- `app/api/`：认证、账号、群组、申请、消息、AI、GitHub、任务、插件、日志、系统、OneBot、Webhook、WebSocket 路由。
- `app/services/account_manager.py`：每个账号独立运行时和适配器；支持连接状态、指数退避、跨进程数据库租约。
- `app/services/bot_engine.py`：事件落库后按自动管理 → 命令 → AI → 插件钩子处理。
- `app/services/scheduler.py`：独立 `scheduler` Compose 服务可加载数据库任务；任务执行仍直接调用共享业务服务。
- `app/core/events.py`：进程内事件信封为 `type/id/time/data`，当前不提供跨进程广播。

## 进程与部署模式

Compose 服务为 `postgres`、`redis`、`backend`、`scheduler`、`frontend`、`nginx`；`worker` 需显式启用 `--profile workers`，已具备 Redis 队列消费者：仅当 `REDIS_ENABLED=true` 且 `REDIS_QUEUE_ENABLED=true`、外部 Redis 可用时消费并调用任务执行器，真实部署尚未验收。NapCat 需 `--profile napcat`，示例只配置一个 `napcat-1`，多账号应复制独立实例与持久化卷。

## 关键数据流

1. OneBot 事件由 HTTP `/api/onebot/v11/events/{account_uid}` 或反向 WS 接收，校验账号 token 后进入适配器事件流。
2. AccountManager 将事件交给 BotEngine；消息、群成员、申请和操作结果写入数据库。
3. GitHub Webhook 先做 HMAC-SHA256 验签，再按 delivery/release 去重；轮询由 APScheduler 触发。
4. 前端通过 REST 获取页面数据，通过 `/api/ws/status`、`/api/ws/logs` 或 `/api/ws/events` 获取实时状态/日志。

## 扩展边界

OneBot v11 是协议适配边界；不支持的动作通过能力检测返回明确错误。插件通过清单声明权限和按账号/群绑定，但动态 Python 插件仍必须在受信环境运行。水平扩展前需将连接管理与 EventHub 迁移到独立连接服务和共享事件/租约机制。