# 在线更新与发布

## 适用范围

QBot AI 在后台检测 GitHub 正式发布。原生 Linux 部署安装独立升级服务后，可在网页点击「立即升级」，由服务器完成下载、备份、安装和服务重启。Docker / 自定义部署按原有部署流程升级。

1. GitHub Releases 作为稳定版本源。
2. 管理台启动后按间隔检查 `/api/system/update`，设置页可手动检查。
3. GitHub Actions 在 `main` 的 push / PR 上执行测试和 Docker 构建检查。
4. 推送 `vMAJOR.MINOR.PATCH` 标签后，Actions 重新验证、打包源码、生成 SHA-256 清单并创建 GitHub Release。
5. 原生部署使用后台「立即升级」；其他部署由管理员下载并校验 Release，执行对应的备份、升级、迁移和健康检查。

## 版本检查

后端配置项：

```dotenv
UPDATE_REPOSITORY=yuchen0x1/AI-QQ-Bot
UPDATE_CHANNEL=stable
UPDATE_CHECK_INTERVAL_MINUTES=360
```

`stable` 使用 GitHub 的 latest release；`beta` 会从非草稿发布中选择最近的预发布版本。版本比较遵循 SemVer，远程版本低于当前版本时不会提示降级。网络失败只显示诊断，不阻塞应用启动。

更新接口返回当前版本、最新版本、Release 地址、发布时间、更新日志、资产大小和 GitHub 提供的 SHA-256 digest（若资产存在）。下载地址只接受 HTTPS GitHub 资产地址。

## 发布新版本

1. 在 `main` 上完成代码、测试和文档。
2. 将后端 `backend/app/core/version.py`、前端 `frontend/package.json` 及 `frontend/package-lock.json` 更新为同一 SemVer 版本；在 `docs/releases/release-notes.md` 添加对应版本的更新说明。
3. 提交并推送 `main`，确认 CI 通过。
4. 创建并推送标签：

   ```bash
   git tag v1.1.1
   git push origin v1.1.1
   ```

5. `release.yml` 会校验标签与前后端、锁文件版本一致且存在对应的更新说明；运行后端测试/Ruff、前端构建和两个 Docker 镜像构建，再生成源码、ZIP 上传包、带完整前端的 `qbot-ai-<version>-native.tar.gz` 升级包与 `SHA256SUMS`，最后使用对应版本的更新说明创建 Release。将附件下载到同一目录即可执行 `sha256sum -c SHA256SUMS`。

工作流不会覆盖已有 Release；同名标签的发布失败后应修复工作流或重新选择未占用版本号。正式发布仍需要维护者明确创建标签，不会因普通 push 自动发布。

## 服务器升级

原生 Linux 的安装方式和恢复流程见 [原生部署与一键升级](NATIVE_SERVER.md#安装网页一键升级)。升级服务独立于机器人进程运行，因此后端重启不会中断安装。网页会显示进度并在服务恢复后自动刷新；启动检查未通过时会恢复旧版本及数据备份。升级前始终保留原环境配置与密钥。

Docker 部署示例：

```bash
# 下载 Release 资产后，在隔离目录校验
sha256sum -c SHA256SUMS

# 备份、构建、迁移、重启并检查
./backup.sh
docker compose config --quiet
docker compose up -d --build
docker compose exec backend alembic upgrade head
curl -f http://127.0.0.1:8080/api/system/health
```

健康检查返回 HTTP 503 时，不能继续接收流量，应先查看 backend/PostgreSQL/Redis 日志。数据库迁移前必须保留备份；恢复流程见 `restore.sh` 和 `DEPLOYMENT.md`。

## 安全边界与已知限制

- 当前发布资产使用 SHA-256 完整性校验；没有代码签名证书或发布私钥，因此不能声称完成 Windows/容器代码签名。
- GitHub Actions 使用仓库内置 `GITHUB_TOKEN`，不需要提交个人 Token。工作流不包含自动 SSH 生产部署，因为服务器地址、SSH 密钥和回滚策略尚未授权配置。
- Release 检查依赖 GitHub API；API 不可访问时应用继续运行，但不会显示最新版本。
- 原生安装由独立宿主机升级服务执行，普通网页进程不持有任意 shell / root 执行入口；没有安装升级服务的部署会明确显示不可用原因。
- 远程版本低于本地版本时不会触发降级提示，避免误回滚。
