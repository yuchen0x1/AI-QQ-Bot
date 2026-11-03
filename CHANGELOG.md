# CHANGELOG

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