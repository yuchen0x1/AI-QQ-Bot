# PROJECT_AUDIT

审计日期：2026-11-03

## 结论摘要

- **已完成**：FastAPI + SQLAlchemy 异步后端、Vue 3/TypeScript 控制台、OneBot v11 接入边界、Mock 适配器、JWT/RBAC、登录锁定、请求限流、敏感字段加密、审计日志、GitHub Webhook/轮询、AI Provider、APScheduler、插件目录同步、Docker Compose 基础编排。
- **部分完成**：跨进程账号租约已加入 `account_connections`；统一进程内事件总线和 `/api/ws/events` 已加入；Worker 已具备 Redis 队列消费者，但仅在 workers profile、队列开关开启且外部 Redis 可用时运行，真实部署尚未验收。
- **待外部配置**：生产 PostgreSQL/Redis、TLS 反向代理、真实 OneBot/NapCat、GitHub Token/Webhook、AI Provider 密钥、备份异地存储。
- **未完成/限制**：后端 WebSocket 状态仍含兼容旧字段；水平扩展机器人连接、生产恢复演练和公网安全验收未完成。前端类型错误已修复并通过生产构建。

## 检查范围

`backend/app`、`backend/migrations`、`backend/tests`、`frontend/src`、`docker-compose.yml`、`nginx/default.conf`、`.env.example`、`README.md`、`backup.sh`、`restore.sh` 与 `backend/pytest_out.txt`。

## 关键发现

1. 数据模型由 `backend/app/models/__init__.py` 统一导入；Alembic 当前链为 `0001_initial -> 0002_bot_requests -> 0003_runtime_leases`。
2. `backend/app/db/init_db.py` 启动时仍执行 SQLAlchemy `create_all` 并写入角色、管理员、系统设置、命令和插件，迁移不会自动升级既有数据库。
3. Docker 默认仅将 Nginx 端口绑定到 `HTTP_BIND`，默认回环；PostgreSQL、Redis、NapCat WebUI 未直接发布宿主端口。
4. 登录支持 JWT Bearer 或 HttpOnly Cookie；生产启动会拒绝默认/过短 `SECRET_KEY`、默认/过短 `ADMIN_PASSWORD` 和通配 CORS。
5. 插件使用动态 Python 导入。代码层通过 `PluginContext` 暴露受限接口和权限声明，但动态导入本身仍应视为受信代码执行，插件包需来源审查。
6. `backend/pytest_out.txt` 是历史结果，显示 `test_failed_push_then_retry` 曾因离线账号被误认为可推送而失败；按当前测试配置重新运行时该问题已通过。

## 验证结果

- `PYTHONPATH=backend python -m pytest -q -c backend/pytest.ini backend`：**43 passed**。
- `python -m ruff check backend/app backend/tests`：**All checks passed**。
- `npm --prefix frontend run build`：后续复测已通过 `vue-tsc -b` 和 Vite 生产构建（2326 modules transformed）。
- `docker compose config --quiet`：未提供 `.env` 时按必填变量设计失败，需复制并填写 `.env.example`。

## 不应执行的操作

审计期间未删除、重置、清空或恢复任何数据库；`restore.sh` 仅作为文档审查对象，实际恢复必须人工输入 `RESTORE` 并使用隔离环境。