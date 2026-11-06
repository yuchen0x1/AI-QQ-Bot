# DEPLOYMENT

## 生产 Compose 部署

1. 安装 Docker Engine 和 Compose v2，将项目放到 Linux 主机。
2. 复制环境模板并填写随机凭据：

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

至少填写 `SECRET_KEY`、`ADMIN_PASSWORD`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`，并配置 `PUBLIC_BASE_URL`、`CORS_ORIGINS`。QQ 官方机器人的 AppID / AppSecret 在后台账号表单中填写并加密入库，不写入 `.env`；只有启用旧 NapCat 接入时才需要 `NAPCAT_WEBUI_TOKEN`。`.env` 不得提交版本库。

3. 先校验配置，再启动：

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs -f backend scheduler
```

QQ 官方机器人接入默认 `docker compose up -d --build` 即可，无需任何 profile 或公网回调地址；backend 需能出站访问 `bots.qq.com`、`api.bot.qq.com`（沙箱 `sandbox.api.sgroup.qq.com`）及网关返回的 `wss` 地址。仅在仍使用内置 NapCat 时追加 `--profile napcat`；需要队列执行时追加 `--profile workers`，并在 `.env` 设置 `REDIS_ENABLED=true`、`REDIS_QUEUE_ENABLED=true` 及可达的 Redis URL。Worker 已具备 Redis 队列消费者，会从队列取任务并调用任务执行器；该模式尚未完成真实目标环境部署验收。

4. 首次/升级数据库先备份，再执行迁移：

```bash
docker compose exec backend alembic upgrade head
```

应用启动也会自动执行 `alembic upgrade head`，随后单独写入幂等种子数据，不再使用 `create_all`。缺少 `alembic_version` 的旧库或版本不在当前迁移链中时会拒绝启动并输出 `SchemaVersionError`；请先备份并核对 schema，确认与 head 一致后执行 `alembic stamp head`，不一致时补充迁移。核对 `alembic current` 和应用日志。

## 网络与 TLS

默认 `HTTP_BIND=127.0.0.1`、`HTTP_PORT=8080`，由宿主机已有 TLS 反向代理或 SSH 隧道访问。若设置 `0.0.0.0`，必须同时配置 HTTPS、IP allow-list、防火墙和强管理员凭据；禁止直接公网暴露管理端口、PostgreSQL、Redis 或 NapCat 6099 WebUI。Nginx 容器负责 SPA、`/api/` 代理和 `/ws/` 升级头。

## QQ 官方机器人（默认接入）

1. 在 QQ 开放平台创建机器人并在「开发基础设置」选择回调方式（与后台账号表单保持一致）：**WebSocket**（订阅群聊 @ 消息 / 单聊消息事件，Intents `33554432`）或 **Webhook**（回调地址填 `https://你的域名/api/qqbot/webhook/{AppID}`，平台仅允许 80/443/8080/8443 端口，保存时自动完成 op=13 地址验证；生产必须走 HTTPS 并确保反代透传 `X-Signature-Ed25519` / `X-Signature-Timestamp` / `X-Bot-Appid` 请求头）。
2. 在「服务器 IP 白名单」加入服务器公网出口 IPv4；沙箱环境不受白名单限制，适合先联调。
3. 后台「QQ 账号管理 → 添加机器人」填写 AppID / AppSecret，开发阶段勾选沙箱，需要定时推送时开启「允许主动消息」。
4. 点「测试连接」确认凭据与网关可达，再点「启动」。群里必须 @ 机器人才能触发事件；单聊需先添加机器人好友。
5. 平台不提供群管理 / 申请审批 / 全量列表接口，能力页会如实标记；被动回复 5 分钟内有效（群 5 次、单聊 4 次），主动消息受平台频控。详见 README「官方机器人与 OneBot v11 的能力差异」。

## NapCat / OneBot（兼容旧接入）

每个 QQ 账号使用独立 NapCat 实例、独立配置卷和访问 token。backend 通过内部网络访问 `webui_url`、HTTP API 和 WS；后台扫码只用于受控内网。也可在后台使用高级 OneBot 接入填写 API/WS 地址和 token。真实协议端上线前先用 Mock 账号完成功能验收。官方机器人接入不需要 NapCat。

## GitHub OAuth（可选）

1. GitHub → Settings → Developer settings → OAuth Apps → New OAuth App；`Homepage URL` 填站点地址，`Authorization callback URL` 必须是 `${PUBLIC_BASE_URL}/api/github/oauth/callback`（例如 `https://xiaoshuo.lenmo.top/api/github/oauth/callback`）。
2. 两种配置方式：后台「GitHub 仓库监控 → 配置 OAuth App」填写（存在 `system_settings.github_oauth`，Client Secret 加密，改完立即生效）；或在 `.env` 设置 `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` 后重启 backend。
3. 反向代理必须原样透传 `Host` 与 `X-Forwarded-*`，否则回调地址与前端跳转会不一致；本地开发（前端 5173 代理 `/api`）需额外设置 `GITHUB_OAUTH_REDIRECT_URI=http://127.0.0.1:5173/api/github/oauth/callback`。
4. 授权范围默认 `read:user repo`；只监控公开仓库可改为 `read:user public_repo`（OAuth App 没有只读的 `repo` 权限）。
5. 排障：回调后页面提示 `github=error` 时，先核对回调地址与 Client Secret 是否一致；`redirect_uri_mismatch` 表示 GitHub 侧登记的地址与请求不一致；`bad_verification_code` 表示 code 已被使用或超过有效期（需重新发起绑定）。

## 备份、恢复和升级

```bash
./backup.sh
./restore.sh backups/qbot-YYYYMMDD-HHMMSS.sql.gz
```

恢复会覆盖数据库对象，脚本要求输入 `RESTORE`；只在隔离环境演练，生产恢复前另做当前备份。将 `backups/` 复制到独立、加密且访问受控的存储，并定期验证可恢复性。升级顺序建议：备份 → 拉取代码 → `docker compose config` → 构建 → `alembic upgrade head` → 重启 → 健康检查。

## 健康检查与排障

- `docker compose ps`：确认 postgres/redis health 和 backend/frontend/nginx 状态。
- `curl http://127.0.0.1:8080/api/system/health`：检查应用健康。
- 登录失败：检查初始环境变量；已有用户不会因修改 `.env` 自动改密。
- 账号离线：官方机器人检查回调方式、AppID/AppSecret、Intents 权限、IP 白名单、出站网络与账号日志中的 `err_code`；旧 OneBot 接入检查内部地址、token、NapCat 状态和账号日志；不要把 Mock 在线当作真实 QQ 在线。
- Webhook 409：当前实现统一要求配置 Secret；Webhook 401：核对 Secret、签名头、GitHub delivery 日志。开发/测试覆盖无密钥路径应使用专门测试替身，不要放行真实端点。
- AI 失败：检查 Base URL、模型名、密钥和出站网络；接口不会回显完整 key。
- 迁移失败/启动报 `SchemaVersionError`：停止发布，保留备份，核对 `alembic_version` 和目标 schema；版本缺失时备份核对后用 `alembic stamp head` 纳管，禁止用删库重建作为修复手段。