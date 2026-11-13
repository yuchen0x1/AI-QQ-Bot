# QBot AI 多账号智能 QQ 机器人管理平台

面向 Linux 服务器的模块化 QQ 机器人管理控制台：使用 **QQ 开放平台官方机器人**，支持多账号隔离、群聊、AI 多供应商、GitHub 仓库动态、QQ 群推送、失败邮件、持久化定时任务与插件扩展。

> QQ 接入仅支持官方机器人：凭 AppID + AppSecret 获取官方 AccessToken，通过 WebSocket 或签名验证的 Webhook 收发事件。管理端默认监听本机回环地址，生产部署需配置 TLS、访问控制和强密码。

## 最新更新

### v1.2.0（2026-11-14）

- QQ 接入统一使用官方机器人，支持 WebSocket 与 Webhook，移除旧扫码及其他协议选项。
- GitHub Token 一次连接全部仓库，多群独立绑定与推送，支持提交、Issue、PR、评论和版本发布；仓库删除后自动更新监控清单和计数。
- 首次使用提供分步教学、可搜索操作文档和 QQ 设置实图；失败邮件可在后台配置发信账号与收件人。
- 提供服务器上传包与原生 Linux 常驻服务、HTTPS 反向代理配置。

完整记录见 [更新历史](docs/releases/release-notes.md)。

## 当前实现

- 首次登录分步教学与可搜索的操作文档；后台可配置 Agent Mail / SMTP 发信账号、收件邮箱、失败提醒类型和发信测试，邮件队列与重试持久化。见 [首次使用与失败邮件](docs/FIRST_USE_AND_EMAIL.md)。
- GitHub 仓库清单约每分钟同步，删除或不可访问的自动接入仓库退出当前列表与计数、暂停监控并保留历史；仪表盘和仓库表自动刷新。

- 全部仓库动态群通知：Token 一次连接、自动发现新仓库、多个通知群独立启停、群号显示、群内一次性口令绑定；支持提交、PR、Issue、评论、Release 等事件，以及服务器自动配置实时 Webhook。操作和部署见 [全部仓库通知指南](docs/GITHUB_NOTIFICATIONS.md)。

- FastAPI + SQLAlchemy 2 异步 ORM；PostgreSQL 生产库，SQLite 便于本地测试；Alembic 迁移入口。
- JWT 登录、密码哈希、登录失败锁定、RBAC 权限、敏感配置加密、操作审计和请求限流。
- TOTP 两步验证（二维码绑定、验证码启用/关闭、challenge 防重放）与数据库登录会话管理：查看活跃设备、撤销单个/其它会话，改密、重置密码、关闭 2FA 时自动作废旧令牌，API 与 WebSocket 均校验会话有效性。
- 官方机器人多账号运行时：AppAccessToken、Gateway WebSocket / Webhook、Identify / Heartbeat / Resume、回调地址验证、Ed25519 验签、被动与主动消息、OpenID 映射、连接状态与退避重连。
- 群聊配置、命令权限、消息统计、历史申请记录与审计；具体操作按官方适配器已实现的能力开放。
- OpenAI 兼容 Provider、多模型管理、密钥脱敏、模型调用/测试、会话上下文与失败降级。
- GitHub 仓库 CRUD、Release/Tag 轮询、Webhook HMAC 验签、事件/版本/推送去重、AI 更新摘要、失败重试及推送历史。
- GitHub OAuth 授权：网页绑定自己的 GitHub 账号后一键列出/批量导入仓库（含私有），Token 加密存储且不回显；仓库按添加者隔离，普通用户只能看到自己的仓库。
- APScheduler 持久化任务和执行记录；插件目录扫描、按账号/群绑定。
- Vue 3 + TypeScript + Element Plus 管理控制台：仪表盘、账号、群聊、申请审核、消息、AI、仓库、推送规则/记录、任务、插件、日志、系统监控、系统设置。
- Docker Compose 服务：frontend、backend（内置 APScheduler）、postgres、redis、nginx；`worker` 扩展入口可通过 `--profile workers` 显式启动，只消费不需要机器人连接的队列任务。

目前 WebSocket 连接由现有单进程运行时管理；官方机器人重连时优先使用 Gateway 的 Resume 恢复会话。若要水平扩展 backend，应先将机器人连接管理迁移到独立的连接服务并增加分布式租约/锁，避免同一账号多实例重复连接。**调度器必须与机器人连接同进程**：GitHub 推送、定时群消息、群聊 AI 总结都调用 `account_manager.send_group_message()`，而 adapter 只存在于持有连接的 backend 进程内，拆到独立容器会因运行时表为空而全部失败。`app/scheduler_runner.py` 仅作为连接服务分离后的实验性入口保留，启动时会打印明确警告。Worker 已具备 Redis 队列消费者，但默认通过 Compose profile 关闭；它只会收到备份、数据清理、健康检查这类不需要 adapter 的任务（连接相关任务由 `CONNECTION_BOUND_TASKS` 挡在队列之外），启用条件是 `workers` profile + `REDIS_ENABLED=true` + `REDIS_QUEUE_ENABLED=true` 且外部 Redis 可用。

## Linux Docker Compose 部署

1. 安装 Docker Engine、Docker Compose v2，将仓库复制至 Linux 服务器。
2. 配置环境变量并生成不可预测的强密码：

   ```bash
   cp .env.example .env
   python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
   # 用生成的值填写 SECRET_KEY；并替换 POSTGRES_PASSWORD、REDIS_PASSWORD、ADMIN_PASSWORD。
   ```

   `.env` 包含凭据，勿提交版本库。建议 `HTTP_BIND=127.0.0.1`，由受访问控制的 HTTPS 反向代理接入。AppID / AppSecret 不写在 `.env`，在后台账号表单中填写并加密入库。
3. 启动服务：

   ```bash
   docker compose up -d --build          # 官方机器人接入
   docker compose ps
   docker compose logs -f backend
   ```

   页面默认 `http://127.0.0.1:8080`；本地访问受限时通过 SSH 隧道或自行设置 TLS 代理。初始管理员账号/密码取自 `.env` 中的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`，生产环境必须使用至少 12 位随机密码（不要使用 `admin123`），首次登录后请立即修改密码。
4. 运行数据库迁移（应用启动会自动执行 `alembic upgrade head`，再写入种子数据；推荐升级前手动预执行并核对版本）：

   ```bash
   docker compose exec backend alembic upgrade head
   ```

   从旧版本升级时会执行 `0004_qq_official`，新增账号凭据列与 `qq_official_identities` 映射表；升级前请先备份。
5. 接入 QQ 官方机器人（推荐，不再扫码登录）：

   1. 在 QQ 开放平台完成主体认证并创建机器人；「设置 AI 服务」选择「稍后连接」以使用自建服务。
   2. 在机器人「开发基础设置 → 事件订阅与回调地址」选择回调方式（二选一，需与后台账号表单一致）：
      - **WebSocket**（推荐，无需公网回调地址）：订阅「群聊 @ 机器人消息 / 单聊消息」等事件（对应 Intents `1 << 25` = `33554432`）；
      - **Webhook**：把回调地址设为 `https://你的域名/api/qqbot/webhook/{AppID}`（平台仅允许 80/443/8080/8443 端口），保存时平台会推送 `op=13` 验证请求，backend 用 AppSecret 派生 Ed25519 私钥自动应答；事件推送用 `X-Signature-Ed25519` 验签。Webhook 模式下事件接收范围在平台侧按「全部接收 / 部分接收」选择，账号表单中的 Intents 不生效。
   3. 在「服务器 IP 白名单」加入服务器公网出口 IP（沙箱环境不受白名单限制）；未设置白名单时平台可能拒绝提审/上线。
   4. 在「开发设置」取得 **AppID（BotAppID）** 与 **AppSecret（ClientSecret）**。
   5. 后台「QQ 账号管理 → 添加机器人」填写名称、AppID、AppSecret；本地调试可勾选「沙箱环境」；需要定时推送、群聊总结、GitHub Release 通知时保持「允许主动消息」开启（机器人需具备主动消息权限）。
   6. 点击「测试连接」验证凭据与网关，再点「启动」。把机器人拉进群后在群里 **@ 机器人** 即可触发命令 / AI / 插件；单聊直接发消息即可。

   官方平台只给字符串 OpenID，本平台会自动把 `group_openid` / `user_openid` / `member_openid` 映射成稳定的内部整数 ID 持久化到 `qq_official_identities`，因此群聊、消息、AI 会话、统计等页面照常工作。**页面显示的群号 / 用户号是内部映射 ID，不是真实 QQ 号或群号。** 群与用户只在机器人被拉入群或收到消息后才登记，官方平台不提供全量群列表 / 成员列表接口。

6. 监控仓库：后台添加公开仓库 URL；私有仓库配置 GitHub Token。创建推送规则，选择发送账号和群号（官方机器人请填平台已登记的映射群 ID）。Webhook 页面可查看签名密钥状态和回调地址；在 GitHub 仓库 Settings → Webhooks 中配置 `Release` 事件及相同 Secret。轮询作为备用。
7. （可选）绑定 GitHub 账号：在 GitHub → Settings → Developer settings → OAuth Apps 新建应用，`Authorization callback URL` 填 `https://你的域名/api/github/oauth/callback`；回到「GitHub 仓库监控」，有「系统设置」权限的账号点「配置 OAuth App」填入 Client ID / Client Secret（加密入库，也可用 `GITHUB_OAUTH_CLIENT_ID/SECRET` 环境变量），保存后点「绑定 GitHub 账号」。绑定完成即可「从 GitHub 导入」批量勾选仓库，无需逐个粘贴 Token。导入的仓库不复制 Token，运行时按归属用户动态取用。
8. 配置 AI：添加 Provider 的 Base URL / API Key，再创建模型并测试。API Key 加密存储，服务接口不会回传完整密钥。

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
- 生产验证恢复流程时请使用隔离环境；备份文件可能含个人信息与凭据（含加密后的 AppSecret），应限制访问。

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

## 在线更新与发布

项目使用 GitHub Releases 作为在线版本源。管理台启动后会检查稳定版本，系统设置页可手动查看当前版本、Release、更新日志、发布资产和 SHA-256；Web 项目不会在浏览器内自动替换服务端文件。推送 `vMAJOR.MINOR.PATCH` 标签后，`.github/workflows/release.yml` 会运行测试、构建 Docker 镜像、打包源码并生成 `SHA256SUMS`，服务器按 `docs/AUTO_UPDATE.md` 校验后执行 Docker Compose 更新。

完整流程、Beta 通道、GitHub Actions、回滚和未配置代码签名的限制见 [docs/AUTO_UPDATE.md](docs/AUTO_UPDATE.md)。

Vite 开发服务器默认端口 5173，`/api` 代理到 `http://127.0.0.1:8000`。本机 5173 端口若被其他程序占用，Vite 会提示并自动选择下一个可用端口；启动日志会给出实际访问地址。

本地调试官方机器人：后端需要能访问 `bots.qq.com`、`api.bot.qq.com`（沙箱为 `sandbox.api.sgroup.qq.com`）及网关返回的 `wss` 地址。在后台账号表单填写 AppID / AppSecret 并勾选沙箱即可，无需公网 IP 或回调域名。如域名需要走代理，可用 `QQBOT_OPENAPI_BASE` / `QQBOT_SANDBOX_OPENAPI_BASE` / `QQBOT_TOKEN_URL` 或在账号的「OpenAPI 域名」中覆盖。生产部署不要复制本地 `backend/.env`。

## 测试与检查

```bash
cd backend
python -m pytest -q
ruff check app tests
cd ../frontend && npm run build
```

测试使用独立临时 SQLite、HTTP / WebSocket mock 和 `backend/tests/fakes.py` 中的测试替身，不连接真实外部平台。测试替身不会被应用工厂加载，也不作为后台可选协议。生产验收仍需真实官方机器人、GitHub、邮箱或 AI 凭据与 Linux Docker 主机。

## 重要 API

- Swagger：`/api/docs`（登录以外端点由 JWT + RBAC 保护）
- 健康检查：`/api/system/health`
- WebSocket 日志：`/api/ws/logs`（携带 JWT Token）
- GitHub Webhook：`/api/webhook/github/{repo_id}`
- 账号管理：`POST/PUT /api/accounts`（`protocol=qq_official` 时传 `app_id` / `app_secret` / `official_*`）、`POST /api/accounts/{id}/test-connection`、`GET /api/accounts/{id}/capabilities`

官方机器人由 backend 接入平台：**WebSocket 模式**主动连接 Gateway，不需要公网回调地址；**Webhook 模式**不需要出站长连接，但要求平台能访问公网 HTTPS 回调地址 `https://你的域名/api/qqbot/webhook/{AppID}`（Nginx 已内置 `=/webhook` 兼容转发）。Webhook 模式的账号「在线」表示本地就绪，平台验证通过后才会真正推送事件；多实例部署时回调只会命中持有该账号运行租约的实例，其它实例返回 503 由平台重试。两种模式在账号表单的「回调方式」中选择，必须与开放平台设置一致。

## 官方机器人能力范围

| 能力 | 当前实现 |
|---|---|
| 接入 | AppID + AppSecret，WebSocket 或验签 Webhook |
| 群聊与单聊 | 官方平台消息、命令与 AI 回复 |
| 仓库群通知 | 群内一次性绑定，启用 QQ 主动发送授权后投递 |
| 群与用户标识 | 平台 OpenID 持久映射，真实群号作为显示标签 |
| 管理与审批 | 按当前适配器的 capabilities 开放；未实现的操作明确拒绝 |

旧数据库中的非官方账号升级后会停用并隐藏，关联通知与任务暂停；历史记录保留。新建账号及运行工厂均仅接受官方机器人。

## 部署排障

- **数据库未就绪**：`docker compose ps` 查看 PostgreSQL health；查看 `docker compose logs postgres backend`。
- **后台无法登录**：检查 `.env` 中初始用户名/密码；该初始密码只在首次创建管理员时读取。已有数据库中用户密码应在 Web 设置中更改。
- **官方机器人启动失败**：确认回调方式与账号设置一致、AppID/AppSecret 正确、Intents 已获授权、IP 白名单包含出口 IP、容器可 outbound 访问 `bots.qq.com` 与网关 `wss` 地址；查看账号日志里的 `err_code` 提示。凭据错误会返回明确的 400/鉴权失败信息。
- **Webhook 事件收不到**：确认开放平台回调地址与后台显示的 `webhook_url` 完全一致、平台已显示「验证成功」、账号处于在线状态（未在线时 backend 返回 503 由平台重试）、反代未剥离 `X-Signature-*` 请求头；验签失败会在账号日志记录原因。
- **官方机器人收不到消息**：群里必须 @ 机器人；单聊需先添加机器人好友；沙箱环境只会推送沙箱群 / 沙箱 QQ 号的事件。
- **推送失败 40034105 / 40034100**：机器人无主动消息权限或触发频控（认证 Bot 60 QPM、单关系 20 QPM、每群每天 1000 条）；需在手机 QQ 机器人资料页开启主动消息，或降低推送频率。
- **回复失败 40034005 / 40034128**：被动回复超过 5 分钟或次数用尽；开启「允许主动消息」后适配器会自动降级重发一次。
- **Webhook 返回 401**：确认 GitHub webhook secret 一致，签名头完整；重新发送测试事件并检查应用日志。
- **AI 请求失败**：确认 Base URL、模型 ID、密钥和出站网络；测试 API 会返回服务商错误信息，密钥不会回显。
- **备份失败**：确认 backend 容器内 `pg_dump` 可用并查看 `/backups` 卷权限/剩余空间。备份列表接口以 `size_mb` 返回文件大小。

## 目录

```text
backend/    FastAPI 应用、模型、迁移、适配器、插件、测试
frontend/   Vue 3 + TypeScript 管理控制台
nginx/      反向代理与 SPA 路由配置
data/       本地开发数据（不纳入版本控制）
backups/    本地备份文件（不纳入版本控制）
docker-compose.yml
.env.example
backup.sh / restore.sh
```

## 当前限制和后续工作

- Webhook 回调模式已实现：`op=13` 回调地址验证（AppSecret 派生 Ed25519 签名，与官方 DEMO 逐字节对齐）+ `op=0` 事件推送验签（`X-Signature-Ed25519` / `X-Signature-Timestamp`，默认 300 秒时间窗，可用 `QQBOT_WEBHOOK_MAX_AGE_SECONDS` 调整，0 关闭时间校验）。
- 官方机器人不提供群管理、申请审批、撤回他人消息及全量资料查询接口；相应能力页会明确标记不支持。
- 官方群事件只在用户 @ 机器人时下发，群列表与成员列表来自平台已感知的 OpenID，不是全量同步。
- 前端已通过 `useRealtimeSocket` 连接状态 WebSocket，并用 Pinia 单例（`stores/status.ts`，引用计数）收敛为一条连接，避免多页面重复订阅；跨实例实时事件尚未实现。
- Docker Compose 配置了独立 worker 扩展入口；调度默认在 backend 进程内执行（与机器人连接同进程），启用 `REDIS_QUEUE_ENABLED=true` 后只把不需要 adapter 的任务入队，由 workers profile 中的 Worker 消费；该部署模式仍需目标环境验收。
- 数据库 schema 以 Alembic 迁移为唯一真相：启动时自动 `upgrade head`，之后执行幂等种子数据，不再使用 SQLAlchemy `create_all`。缺少 `alembic_version` 或版本不在迁移链中的旧库会拒绝启动，需备份核对后执行 `alembic stamp head` 或补充迁移。
- 多实例机器人运行、自动化处罚策略的生产灰度、公网 HTTPS/监控告警、恢复演练、Docker/Linux 集成验收仍需在目标服务器完成。

## Star History

<a href="https://star-history.com/#yuchen0x1/AI-QQ-Bot&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=yuchen0x1/AI-QQ-Bot&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=yuchen0x1/AI-QQ-Bot&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=yuchen0x1/AI-QQ-Bot&type=Date" width="720" />
  </picture>
</a>
