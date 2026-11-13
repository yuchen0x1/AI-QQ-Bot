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

## 安装网页一键升级

v1.3.0 起，原生部署支持后台「系统设置 → 在线更新 → 立即升级」。服务器需要使用上述固定目录布局、Python 3.12、systemd 和 SQLite；Docker / 自定义布局仍按各自部署流程更新。

第一次将新版本的升级入口安装到现有服务后，在源码根目录执行一次：

```bash
sudo python3 scripts/updater/install.py
sudo systemctl restart qbot
```

此脚本保留现有环境配置并增加升级服务地址，保存配置与 Nginx 原件；创建独立构建用户及 `qbot-updater.service`。后端服务改用当前发布目录内的 `.venv`；旧部署原有虚拟环境通过符号链接继续使用。请先核对目录布局并备份。

之后在后台检查更新，发现带 `native.tar.gz` 升级包的正式版本时点击「立即升级」。下载、校验和运行环境准备期间旧版本继续工作；切换前暂停外部 API、停止机器人服务并备份数据库。新版本通过启动检查后恢复写入与推送，网页自动刷新。检查失败会恢复旧版本和升级前的数据；升级记录仍保留。

- 升级状态与日志：`/var/lib/qbot-updater/jobs/`，root 专用目录。
- 升级前数据库备份：`/var/lib/qbot-updater/backups/upgrade-<任务标识>.db`，由 root 独占，与应用数据及应用用户可写的日常备份目录分开保存。
- 升级服务仅通过 `/run/qbot-updater/control.sock` 接收后台管理员发起的请求，没有公网管理端口；网页只能提供版本号与请求标识，不能提供下载地址、命令或路径。
- 包只从 root 配置的 GitHub 仓库最新正式发布获取，并按 GitHub 的 SHA-256 digest 校验。依赖安装在独立用户的受限进程中完成，不向构建进程提供应用密钥。
- 升级服务自身被中断时，下次启动会读取持久化状态；已经恢复对外写入的版本不会再自动覆盖数据库。如显示「需要检查」，先查看服务和升级日志再处理，保留备份。

升级服务的 root 配置是 `/etc/qbot/updater.json`；不要将该文件或部署目录的写权限授予机器人用户。宿主机升级服务的代码更新由服务器管理员安装，网页升级不修改宿主机权限配置。
