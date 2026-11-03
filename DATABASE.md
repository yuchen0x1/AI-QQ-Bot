# DATABASE

## 数据库配置

- 生产推荐 PostgreSQL 16 + `postgresql+asyncpg`。
- 本地测试默认使用独立临时 SQLite + `aiosqlite`。
- `backend/app/db/session.py` 创建异步 engine/session；API 依赖通过 `get_db` 获取会话。
- Compose 使用 `postgres_data` 持久化 PostgreSQL、`redis_data` 持久化 Redis、`app_data`/`app_backups` 持久化应用数据与备份。

## 迁移链

```text
0001_initial_schema.py
  └─ 0002_bot_requests.py
       └─ 0003_runtime_leases.py
```

- `0001_initial` 调用 `Base.metadata.create_all` 创建模型元数据。
- `0002_bot_requests` 创建好友/群申请表（可重复执行，`checkfirst`）。
- `0003_runtime_leases` 为 `account_connections` 增加 `lease_owner`、`lease_id`、`lease_expires_at`，为 `scheduled_tasks` 增加 `queue_name`、`job_key` 并建立索引。
- `migrations/env.py` 从 `app.models` 导入完整 metadata，并按 `DATABASE_URL` 在线/离线运行。

推荐命令：

```bash
cd backend
PYTHONPATH=. alembic upgrade head
PYTHONPATH=. alembic current
PYTHONPATH=. alembic history
```

## 主要表域

- 身份：`users`、`roles`、`audit_logs`、`login_attempts`。
- QQ：`accounts`、`account_connections`、`groups`、`group_settings`、`group_members`、`messages`、`bot_requests`。
- AI：`ai_providers`、`ai_models`、`ai_conversations`、`ai_messages`、`ai_usage_logs`。
- 仓库监控：`github_repositories`（含 `provider`，当前支持 GitHub/Gitee）、`github_releases`、`github_events`、`push_rules`、`push_records`。
- 自动化/扩展：`scheduled_tasks`、`task_records`、`plugins`、`plugin_bindings`、`commands`、`system_logs`、`system_settings`。

账号、群、消息和申请均通过外键/唯一约束隔离；例如群唯一键为 `(account_id, group_number)`，申请去重键为 `(account_id, request_type, flag)`，推送记录去重键为 `(rule_id, release_id)`。

## 初始化与升级风险

`app/db/init_db.py` 启动时默认执行 `Base.metadata.create_all`、种子角色/管理员/设置/命令/插件。它适合新库，但不会为既有库执行 Alembic 版本升级；模型字段变更必须先备份，再运行 `alembic upgrade head` 并核对 `alembic_version`。`0001` 使用 create_all 而非逐列迁移，旧库从非标准 schema 升级前应做结构比对。

## 备份与恢复

生产 PostgreSQL 使用 `backup.sh` 调用 `pg_dump --clean --if-exists` 压缩到 `backups/*.sql.gz`，默认保留 14 份；`restore.sh` 会覆盖目标对象并要求输入 `RESTORE`。恢复必须在隔离环境演练，禁止直接对未备份的生产库执行；备份含个人信息和密钥密文，应限制权限并异地保存。