# 原生 Linux 部署与已有数据迁移

此方式适合单机常驻运行，使用 Python 3.12、systemd、Nginx 和原有 SQLite 数据库。无需为迁移改用 PostgreSQL。连接管理和调度器保持在同一个后端进程，禁止同时启动多个持有同一机器人凭据的实例。

## 目录与权限

- `/opt/qbot/releases/<部署标识>`：源码与已构建的 `frontend/dist`，由 root 管理。
- `/opt/qbot/current`：指向当前部署目录的符号链接。
- `/opt/qbot/venv`：Python 虚拟环境，安装 `backend/requirements.txt`。
- `/etc/qbot/qbot.env`：生产配置，root 所有、qbot 组可读，权限 0640。
- `/var/lib/qbot`：SQLite 数据库和独立的 Agent Mail 授权目录，qbot 所有、权限 0700。
- `/var/backups/qbot`：备份目录，qbot 所有、权限 0700。

创建无交互登录的 `qbot` 系统用户。安装 [systemd 服务模板](../scripts/systemd/qbot.service) 后执行 `systemctl daemon-reload` 和 `systemctl enable --now qbot`。后端只监听 `127.0.0.1:8000`，由 Nginx 对外提供 80 / 443。

生产环境至少设置 `ENV=production`、`PUBLIC_BASE_URL`、`FRONTEND_BASE_URL`、`CORS_ORIGINS`、强 `ADMIN_PASSWORD` 和 `SECRET_KEY`。原生 SQLite 路径示例：

```dotenv
DATABASE_URL=sqlite+aiosqlite:////var/lib/qbot/qbot.db
DATA_DIR=/var/lib/qbot
BACKUP_DIR=/var/backups/qbot
PLUGIN_DIR=/opt/qbot/current/backend/plugins
REDIS_ENABLED=false
SCHEDULER_ENABLED=true
AGENTLY_CLI_PATH=/usr/local/bin/agently-cli
TRUSTED_PROXIES=127.0.0.1/32,::1/128
```

## HTTPS 与运行检查

参考 [宿主机 Nginx 模板](../nginx/host-native.conf.example)，替换域名与证书路径。首次签发可使用 Certbot webroot：将 `/.well-known/acme-challenge/` 映射到 `/var/www/qbot-acme`，获取证书后启用 HTTPS 站点。开放 80 / 443 和已有 SSH 端口；不开放后端、数据库或缓存端口。配置续期定时器和成功续期后重载 Nginx 的 deploy hook。

```bash
nginx -t
systemctl status qbot nginx
journalctl -u qbot -n 50 --no-pager
curl --fail https://你的域名/api/system/health
```

## 迁移已有本地配置

1. 先停止旧实例的机器人和调度器，再用 SQLite backup API 生成一致的完整副本；保留迁移前备份。
2. 迁移数据库与原 `SECRET_KEY`。更换该密钥会导致已有 QQ / GitHub / SMTP 密文无法解密。不要将数据库或配置写入公开源码包。
3. 复制数据库时保留账号、群、OpenID 映射、仓库、规则与推送记录；清理副本中的连接租约，使新实例重新获取连接。上线强密码必须同步更新已有管理员密码哈希；仅改环境变量不会修改已有用户密码。迁移后的登录会话应重新建立。
4. 将生产服务器出口 IPv4 加入 QQ 开放平台的服务器白名单，保持平台与后台均为 WebSocket 或均为 Webhook。
5. 启动服务器实例，确认账号在线、仓库同步、通知群权限和历史计数；旧实例保持停止，避免重复推送。
6. Agent Mail 使用操作系统凭据存储；Windows 授权不能视为 Linux 已授权。服务器需从后台「邮件告警」重新连接并验证发信账号。授权完成后发送测试邮件，确认实际结果。

应用自带每日数据备份任务。SQLite 恢复、切换旧版本或更换数据目录前应停止服务并另做当前备份；不得直接覆盖运行中的数据库。
