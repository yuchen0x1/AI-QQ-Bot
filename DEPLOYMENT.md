# DEPLOYMENT

## 生产 Compose 部署

1. 安装 Docker Engine 和 Compose v2，将项目放到 Linux 主机。
2. 复制环境模板并填写随机凭据：

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

至少填写 `SECRET_KEY`、`ADMIN_PASSWORD`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`NAPCAT_WEBUI_TOKEN`（使用 NapCat 时），并配置 `PUBLIC_BASE_URL`、`CORS_ORIGINS`。`.env` 不得提交版本库。

3. 先校验配置，再启动：

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs -f backend scheduler
```

需要内置 NapCat 时追加 `--profile napcat`；需要队列执行时追加 `--profile workers`，并在 `.env` 设置 `REDIS_ENABLED=true`、`REDIS_QUEUE_ENABLED=true` 及可达的 Redis URL。Worker 已具备 Redis 队列消费者，会从队列取任务并调用任务执行器；该模式尚未完成真实目标环境部署验收。

4. 首次/升级数据库先备份，再执行迁移：

```bash
docker compose exec backend alembic upgrade head
```

应用启动的 `create_all` 只适合补齐新表，不代替既有库的 Alembic 升级。核对 `alembic current` 和应用日志。

## 网络与 TLS

默认 `HTTP_BIND=127.0.0.1`、`HTTP_PORT=8080`，由宿主机已有 TLS 反向代理或 SSH 隧道访问。若设置 `0.0.0.0`，必须同时配置 HTTPS、IP allow-list、防火墙和强管理员凭据；禁止直接公网暴露管理端口、PostgreSQL、Redis 或 NapCat 6099 WebUI。Nginx 容器负责 SPA、`/api/` 代理和 `/ws/` 升级头。

## NapCat / OneBot

每个 QQ 账号使用独立 NapCat 实例、独立配置卷和访问 token。backend 通过内部网络访问 `webui_url`、HTTP API 和 WS；后台扫码只用于受控内网。也可在后台使用高级 OneBot 接入填写 API/WS 地址和 token。真实协议端上线前先用 Mock 账号完成功能验收。

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
- 账号离线：确认内部地址、token、NapCat 状态和账号日志；不要把 Mock 在线当作真实 QQ 在线。
- Webhook 409：当前实现统一要求配置 Secret；Webhook 401：核对 Secret、签名头、GitHub delivery 日志。开发/测试覆盖无密钥路径应使用专门测试替身，不要放行真实端点。
- AI 失败：检查 Base URL、模型名、密钥和出站网络；接口不会回显完整 key。
- 迁移失败：停止发布，保留备份，核对 `alembic_version` 和目标 schema，禁止用删库重建作为修复手段。