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
            └─ 0004_qq_official.py
                 └─ 0005_github_oauth.py
                      └─ 0006_auth_security.py
                           └─ 0007_runtime_lease_index.py
```

- `0001_initial` 为显式 DDL 快照，直接创建基线表与索引，不依赖运行时模型定义。
- `0002_bot_requests` 创建好友/群申请表（若表已存在则跳过，兼容旧库）。
- `0003_runtime_leases` 为 `account_connections` 增加 `lease_owner`、`lease_id`、`lease_expires_at` 及索引，为 `scheduled_tasks` 增加 `queue_name`、`job_key` 并建立索引（列/索引已存在时跳过）。
- `0004_qq_official` 为 `accounts` 增加 `app_id`、`app_secret_enc`（Fernet 密文）、`bot_openid` 与索引，并创建 `qq_official_identities`（OpenID → 内部整数 ID 映射，唯一键 `(account_id, kind, scope, openid)`）。列/索引/表已存在时跳过，兼容旧库升级。
- `0005_github_oauth` 创建 `user_github_tokens`（每个平台用户一条 GitHub 绑定，`user_id` 唯一、`github_id` 唯一，`access_token_enc` 为 Fernet 密文），并为 `github_repositories` 增加 `owner_user_id` 与索引，用于按用户隔离仓库。SQLite 的 `ALTER TABLE` 不支持追加外键，该列按软引用处理，删除用户时由应用层置空；列/索引/表已存在时跳过。
- `0006_auth_security` 增加 TOTP 字段与可撤销登录会话表。
- `0007_runtime_lease_index` 为已有数据库补齐 `account_connections.lease_id` 唯一索引，修复早期迁移已到 head 但索引缺失的情况；重复执行安全幂等。
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
- QQ：`accounts`、`account_connections`、`groups`、`group_settings`、`group_members`、`messages`、`bot_requests`、`qq_official_identities`。
- AI：`ai_providers`、`ai_models`、`ai_conversations`、`ai_messages`、`ai_usage_logs`。
- 仓库监控：`github_repositories`（含 `provider`，当前支持 GitHub/Gitee；`owner_user_id` 记录添加者）、`github_releases`、`github_events`、`push_rules`、`push_records`。
- GitHub 授权：`user_github_tokens`（`user_id` 唯一、`github_id` 唯一、`login`/`avatar_url`/`scopes` 展示用、`access_token_enc` 加密存储、`last_used_at` 记录最近调用）。OAuth App 凭据存放在 `system_settings` 的 `github_oauth` 键中，`client_secret_enc` 同样为密文。
- 自动化/扩展：`scheduled_tasks`、`task_records`、`plugins`、`plugin_bindings`、`commands`、`system_logs`、`system_settings`。

账号、群、消息和申请均通过外键/唯一约束隔离；例如群唯一键为 `(account_id, group_number)`，申请去重键为 `(account_id, request_type, flag)`，推送记录去重键为 `(rule_id, release_id)`，官方机器人 OpenID 映射唯一键为 `(account_id, kind, scope, openid)`。官方账号的 `qq_number` 只是可选备注，`self_id` 为 AppID 数值，群号 / 用户号为 `qq_official_identities.id`。

## 初始化与升级

`app/db/init_db.py` 启动时先调用 `app/db/migrations.py` 将 schema 升级到 Alembic head，再单独执行幂等种子数据（角色、管理员、系统设置、命令、插件）；应用不再执行 `Base.metadata.create_all`。空库会自动建表，已记录 `alembic_version` 且落后于 head 的库会自动升级。

缺少 `alembic_version` 的旧库，或记录的版本不在当前迁移链中时，启动会抛出 `SchemaVersionError` 并拒绝服务，不会静默建表。处理方式：先备份并核对现有 schema；确认与 head 一致后执行 `alembic stamp head`，不一致时先补充缺失迁移。禁止删库重建。

修改模型后先执行 `alembic revision --autogenerate -m "..."` 并人工审查生成内容；可用 `alembic check` 核对迁移后的 schema 与模型是否一致。

## 备份与恢复

生产 PostgreSQL 使用 `backup.sh` 调用 `pg_dump --clean --if-exists` 压缩到 `backups/*.sql.gz`，默认保留 14 份；`restore.sh` 会覆盖目标对象并要求输入 `RESTORE`。恢复必须在隔离环境演练，禁止直接对未备份的生产库执行；备份含个人信息和密钥密文，应限制权限并异地保存。
