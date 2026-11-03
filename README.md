# QBot AI 多账号智能 QQ 机器人管理平台

面向 Linux 服务器的模块化 QQ 机器人管理控制台：多 OneBot v11 账号隔离、群管理、AI 多供应商、GitHub Release 监控、QQ 群推送、持久化定时任务、插件扩展。

> QQ 接入说明：本项目以 OneBot v11 为协议边界。请使用 NapCat、Lagrange 等兼容实现，并遵守 QQ 平台规则及对应实现的许可。默认只在本机回环地址提供 Web 入口；生产部署需配置 TLS、访问控制和强密码。

## 当前实现

- FastAPI + SQLAlchemy 2 异步 ORM；PostgreSQL 生产库，SQLite 便于本地测试；Alembic 迁移入口。
- JWT 登录、密码哈希、登录失败锁定、RBAC 权限、敏感配置加密、操作审计和请求限流。
- 多账号运行时、OneBot v11 HTTP/WebSocket 接入、Mock 测试适配器、连接状态与退避重连。
- 群聊配置、成员同步、群管理动作、自动审核、命令权限和消息统计；OneBot 好友/加群申请持久化、去重、RBAC 审批及操作审计。
- OpenAI 兼容 Provider、多模型管理、密钥脱敏、模型调用/测试、会话上下文与失败降级。
- GitHub 仓库 CRUD、Release/Tag 轮询、Webhook HMAC 验签、事件/版本/推送去重、AI 更新摘要、失败重试及推送历史。
- APScheduler 持久化任务和执行记录；插件目录扫描、按账号/群绑定。
- Vue 3 + TypeScript + Element Plus 管理控制台：仪表盘、账号、群聊、申请审核、消息、AI、仓库、推送规则/记录、任务、插件、日志、系统监控、系统设置。
- Docker Compose 服务：frontend、backend、scheduler、postgres、redis、nginx；`worker` 扩展入口可通过 `--profile workers` 显式启动。

目前 WebSocket 使用现有单进程运行时管理；若要水平扩展 backend，应先将机器人连接管理迁移到独立的连接服务并增加分布式租约/锁，避免同一账号多实例重复连接。`worker` 是后台扩展进程入口，目前为预览/扩展骨架，默认通过 Compose profile 关闭；启用它不会创建一个 Redis 作业消费者。APScheduler 定时任务由独立 `scheduler` 服务执行，任务处理直接调用共享业务服务。

## Linux Docker Compose 部署

1. 安装 Docker Engine、Docker Compose v2。将仓库复制至 Linux 服务器。若使用内置 NapCat 容器，启动时追加 `--profile napcat`；每个 QQ 账号应分配独立 NapCat 服务和独立持久化目录。
2. 配置环境变量并生成不可预测的强密码：

   ```bash
   cp .env.example .env
   python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
   # 用生成的值填写 SECRET_KEY；并替换 POSTGRES_PASSWORD、REDIS_PASSWORD、ADMIN_PASSWORD。
   ```

   `.env` 包含凭据，勿提交版本库。建议 `HTTP_BIND=127.0.0.1`，由受访问控制的 HTTPS 反向代理接入。
3. 启动服务：

   ```bash
   docker compose --profile napcat up -d --build
   docker compose ps
   docker compose logs -f backend scheduler
   ```

   页面默认 `http://127.0.0.1:8080`；本地访问受限时通过 SSH 隧道或自行设置 TLS 代理。默认管理员账号为 `admin`，默认密码为 `admin123`；也可通过 `.env` 中的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 覆盖，首次登录后请立即修改密码。
4. 运行数据库迁移（新库首次启动应用会创建表；后续模型变更需用 Alembic）：

   ```bash
   docker compose exec backend alembic upgrade head
   ```
5. 接入 QQ：推荐在服务器以独立 NapCat 容器提供扫码登录。配置 `NAPCAT_WEBUI_URL`、`NAPCAT_WEBUI_TOKEN`、`NAPCAT_API_BASE`、`NAPCAT_WS_URL` 和 `NAPCAT_INSTANCES_JSON` 后，后台“QQ 账号管理”会显示“扫码添加 QQ”，用户只需扫码；QQ 号码、昵称由登录后的 OneBot 自动获取。NapCat WebUI 端口 6099 只允许内网访问，不挂载 Docker socket，不通过公网 Nginx 转发。已有 OneBot 实例仍可点击“高级 OneBot 接入”，填写 `HTTP API` 地址、WebSocket 地址、访问令牌和模式。测试用 Mock 账号会被明确标记为模拟，不代表真实 QQ 在线。
6. 监控仓库：后台添加公开仓库 URL；私有仓库配置 GitHub Token。创建推送规则，选择发送账号和群号。Webhook 页面可查看签名密钥状态和回调地址；在 GitHub 仓库 Settings → Webhooks 中配置 `Release` 事件及相同 Secret。轮询作为备用。
7. 配置 AI：添加 Provider 的 Base URL / API Key，再创建模型并测试。API Key 加密存储，服务接口不会回传完整密钥。

常用操作：

```bash
docker compose stop
docker compose start
docker compose restart
docker compose pull && docker compose up -d --build
docker compose logs -f --tail=200 backend
```

HTTP 端口仅绑定到 `HTTP_BIND`。若设置 `0.0.0.0`，必须先配置 TLS、强访问控制和防火墙规则，严禁裸露管理端口。

## 备份与恢复

- 手动备份：`./backup.sh`，备份存于 `backups/`，脚本默认保留最近 14 份。
- 手动恢复：`./restore.sh backups/qbot-YYYYMMDD-HHMMSS.sql.gz`，会要求输入 `RESTORE` 确认；恢复前建议另做一份当前数据库备份。
- Compose 数据持久化卷：PostgreSQL `postgres_data`、Redis `redis_data`、应用数据 `app_data`、备份 `app_backups`。定期将备份复制到独立且访问受控的存储。
- 生产验证恢复流程时请使用隔离环境；备份文件可能含个人信息与凭据，应限制访问。

## 本地开发

后端（Python 3.12+）：

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Windows PowerShell 虚拟环境激活命令：`.venv\\Scripts\\Activate.ps1`。初次启动默认 SQLite 数据文件位于项目根目录 `data/qbot.db`；可设置 `DATABASE_URL`、`SECRET_KEY` 和 `ADMIN_PASSWORD` 环境变量。

前端（Node.js 20+）：

```bash
cd frontend
npm ci
npm run dev
npm run build
```

Vite 开发服务器默认端口 5173，`/api` 代理到 `http://127.0.0.1:8000`。本机 5173 端口若被其他程序占用，Vite 会提示并自动选择下一个可用端口；启动日志会给出实际访问地址。

本地扫码登录：项目根目录的 `backend/.env` 可配置本机 NapCat 实例。启动 NapCat 后端口需保持在 `127.0.0.1:6099`（WebUI）、`127.0.0.1:3000`（OneBot HTTP）和 `127.0.0.1:3001`（OneBot WebSocket），再启动后端和前端，进入“QQ 账号管理 → 扫码添加 QQ”。生产部署时不要复制本地 `backend/.env`，改用服务器根目录 `.env`，并将 NapCat 放在 Docker 内部网络，WebUI 不映射公网端口。

## 测试与检查

```bash
cd backend
python -m pytest -q
ruff check app tests
```

测试用独立临时 SQLite 数据库和 HTTP mock，不连接真实 QQ、GitHub 或 AI Provider。本地开发可使用 Mock QQ 账号完成账号生命周期、事件处理和申请审核的端到端验证；不会要求登录真实机器人账号。生产环境验收需额外提供真实 OneBot v11 实例、GitHub Token/Webhook、AI Provider 密钥及 Linux Docker 主机。

## 重要 API

- Swagger：`/api/docs`（登录以外端点由 JWT + RBAC 保护）
- 健康检查：`/api/system/health`
- WebSocket 日志：`/api/ws/logs`（携带 JWT Token）
- GitHub Webhook：`/api/webhook/github/{repo_id}`
- OneBot HTTP 事件入口：`/api/onebot/v11/events/{account_uid}`
- OneBot 反向 WebSocket：`/api/onebot/v11/ws/{account_uid}`

## 部署排障

- **数据库未就绪**：`docker compose ps` 查看 PostgreSQL health；查看 `docker compose logs postgres backend`。
- **后台无法登录**：检查 `.env` 中初始用户名/密码；该初始密码只在首次创建管理员时读取。已有数据库中用户密码应在 Web 设置中更改。
- **账号离线**：扫码模式确认 NapCat 的 WebUI 只在内网可达、OneBot HTTP/WS 地址从 backend 容器可达、账号级 token 匹配；高级模式确认 OneBot 地址从容器网络可达、token 匹配、模式与协议端配置对应；查看账号日志。协议端未接入时不要将模拟适配器误认为真实连接。
- **Webhook 返回 401**：确认 GitHub webhook secret 一致，签名头完整；重新发送测试事件并检查应用日志。
- **AI 请求失败**：确认 Base URL、模型 ID、密钥和出站网络；测试 API 会返回服务商错误信息，密钥不会回显。
- **备份失败**：确认 backend 容器内 `pg_dump` 可用并查看 `/backups` 卷权限/剩余空间。备份列表接口以 `size_mb` 返回文件大小。

## 目录

```text
backend/    FastAPI 应用、模型、迁移、插件、测试
frontend/   Vue 3 + TypeScript 管理控制台
nginx/      反向代理与 SPA 路由配置
data/       本地开发数据（不纳入版本控制）
backups/    本地备份文件（不纳入版本控制）
docker-compose.yml
.env.example
backup.sh / restore.sh
```

## 当前限制和后续工作

- WebSocket 仪表盘页面当前手动刷新；后端日志 WebSocket 可供实时日志集成，尚无前端实时订阅通道。
- Docker Compose 配置了独立 worker 扩展入口；当前业务任务主要由 scheduler 直接执行，尚未启用 Redis 队列。
- 默认数据表初始化通过 SQLAlchemy `create_all`，Alembic 初始版本已提供；从已有数据库升级需先核对 schema 并安排备份。
- QQ 协议覆盖范围取决于 OneBot v11 实现的实际 API 能力；未支持操作会返回明确错误。
- 多实例机器人运行、自动化处罚策略的生产灰度、公网 HTTPS/监控告警、恢复演练、Docker/Linux 集成验收仍需在目标服务器完成。
