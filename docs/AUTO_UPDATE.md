# 在线更新与发布

## 适用范围

QBot AI 在后台检测 GitHub 正式发布。原生 Linux 部署安装独立升级服务后，可在网页点击「立即升级」，由服务器完成下载、备份、安装和服务重启。Docker / 自定义部署按原有部署流程升级。

1. GitHub Releases 作为稳定版本源。
2. 管理台启动后按间隔检查 `/api/system/update`，设置页可手动检查。
3. GitHub Actions 在 `main` 的 push / PR 上执行测试和 Docker 构建检查。
4. 推送 `vMAJOR.MINOR.PATCH` 标签后，Actions 重新验证、运行 Compose smoke、打包源码、生成 SHA-256 清单和 `provenance.sigstore.json`，再创建 GitHub Release。
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

### GitHub 认证与 401 排障

公开仓库的版本检查不需要 Token。`GITHUB_TOKEN` 主要供 GitHub 仓库监控使用；如果服务器上配置了过期、复制错误或已撤销的值，版本检查在收到一次 `401 Bad credentials` 后会自动改用匿名请求重试，不会把本机 Git 凭据带到服务器。Windows 凭据管理器只服务于本机 Git 客户端，不能作为 Linux 服务器调用 GitHub API 的凭据。

服务器仍应清理无效 Token，或按仓库监控所需权限重新生成 Fine-grained Token，然后重启 backend：

```bash
# 不要把 Token 写入命令历史；只在受保护的 qbot.env 中修改
sudoedit /etc/qbot/qbot.env
sudo systemctl restart qbot
# 登录管理台后点击「系统设置 → 在线更新」验证；也可查看后端日志
sudo journalctl -u qbot -n 50 --no-pager
```

如需确认 Token 是否有效，请在服务器上使用临时环境变量调用 GitHub `user` 接口；不要把返回内容或 Token 写入日志。私有更新仓库必须配置可访问该仓库的 Token；公开更新仓库建议留空 `GITHUB_TOKEN`，以避免无关 Token 失效影响版本检查。

## 国内服务器加速

服务器位于中国大陆时，GitHub 直连（尤其是 Release 资产下载）经常被限速或中断。原生升级服务支持在不降低安全要求的前提下走镜像加速，全部配置都在 root 独占的 `/etc/qbot/updater.json`（修改后执行 `sudo systemctl restart qbot-updater`）：

```json
{
  "download_mirrors": ["https://ghfast.top", "https://gh-proxy.com"],
  "pip_index_url": "https://pypi.tuna.tsinghua.edu.cn/simple"
}
```

- `download_mirrors`：升级包下载源，按配置顺序逐个尝试，全部失败后仍回退 GitHub 直连（`api.github.com` 资产接口）。每个来源独立计时，单源 300 秒超时。
- `pip_index_url`：安装依赖使用的 PyPI 镜像（如清华 TUNA、阿里云），留空则使用官方源。

约束与安全边界：

- 镜像地址格式为 gh-proxy 风格前缀，只接受 `https://主机名`（默认 443 端口、不带路径、不带凭据）；不符合的条目会被忽略并直接使用剩余来源。
- 完整性不依赖镜像：版本元数据（含 SHA-256 digest）始终直连 `api.github.com` 获取（瞬时网络错误自动重试一次），镜像只作为下载通道；任何来源下载的升级包都必须通过 digest 校验，重定向只允许回到镜像主机或 GitHub。镜像出现 302 到第三方域名、内容被篡改等情形都会被判为失败并切换下一个来源。
- 公共镜像属于第三方公益服务，可用性经常变化；只用于加速，不改变信任边界。长期生产环境建议自建镜像（例如用 Cloudflare Workers 部署 [gh-proxy](https://github.com/hunshcn/gh-proxy)）再填入 `download_mirrors`。
- 请求镜像时不携带任何 GitHub Token 或应用凭据，泄露面仅限 URL 与 User-Agent。
- 后端的版本检查与仓库动态轮询走 `GITHUB_API_BASE`（默认 `https://api.github.com`），可在 `qbot.env` 中指向自建的 GitHub API 反代；注意公共 gh-proxy 镜像通常只代理文件下载，不代理 API JSON。

## 发布新版本

1. 在 `main` 上完成代码、测试和文档。
2. 将后端 `backend/app/core/version.py`、前端 `frontend/package.json` 及 `frontend/package-lock.json` 更新为同一 SemVer 版本；在 `docs/releases/release-notes.md` 添加对应版本的更新说明。
3. 提交并推送 `main`，确认 CI 通过。
4. 创建并推送标签：

   ```bash
   git tag v1.1.1
   git push origin v1.1.1
   ```

5. `release.yml` 会校验标签与前后端、锁文件版本一致且存在对应的更新说明；复用 CI 运行后端测试/Ruff、前端构建和 Compose smoke，再生成源码、ZIP 上传包、带完整前端的 `qbot-ai-<version>-native.tar.gz` 升级包、`SHA256SUMS` 与 `provenance.sigstore.json`，最后使用对应版本的更新说明创建 Release。将附件下载到同一目录即可执行 `sha256sum -c SHA256SUMS`；原生升级服务还会用 GitHub CLI 验证 `native.tar.gz` 的构建来源证明。

工作流不会覆盖已有 Release；同名标签的发布失败后应修复工作流或重新选择未占用版本号。正式发布仍需要维护者明确创建标签，不会因普通 push 自动发布。

如果发布工作流在上传资产或校验阶段失败，先检查同名草稿，不要重复点击创建 Release：保留资产完整且标签匹配的那一个，删除空草稿和重复草稿，再重新运行修复后的工作流。发布前可用以下命令盘点本地状态；不要删除仍对应开放 Dependabot PR 的远端分支：

```bash
git status --short --branch
git branch -a -vv
git fetch --prune origin
gh release list --repo yuchen0x1/AI-QQ-Bot --limit 20
```

本地仅保留 `main` 作为发布分支；功能和依赖更新通过 PR 合并后由 GitHub/Dependabot 自动清理远端分支。历史标签不强制重写，避免破坏已发布版本的构建证明。

## 服务器升级

原生 Linux 的安装方式和恢复流程见 [原生部署与一键升级](NATIVE_SERVER.md#安装网页一键升级)。升级服务独立于机器人进程运行，因此后端重启不会中断安装。网页会显示进度并在服务恢复后自动刷新；启动检查未通过时会恢复旧版本及数据备份。升级前始终保留原环境配置与密钥。

Docker 部署示例：

```bash
# 下载 Release 资产后，在隔离目录校验
sha256sum -c SHA256SUMS

# 备份、构建、迁移、重启并检查；使用自定义环境文件时同时设置 QBOT_ENV_FILE
./backup.sh
QBOT_ENV_FILE=/绝对路径/qbot.env docker compose --env-file /绝对路径/qbot.env config --quiet
QBOT_ENV_FILE=/绝对路径/qbot.env docker compose --env-file /绝对路径/qbot.env up -d --build
docker compose exec backend alembic upgrade head
curl -f http://127.0.0.1:8080/api/system/health
```

健康检查返回 HTTP 503 时，不能继续接收流量，应先查看 backend/PostgreSQL/Redis 日志。数据库迁移前必须保留备份；恢复流程见 `restore.sh` 和 `DEPLOYMENT.md`。

## 安全边界与已知限制

- 发布资产使用 SHA-256 完整性校验；Release 同时附带由 GitHub Actions OIDC 生成的 Artifact Attestation，原生升级服务在解包前验证 `provenance.sigstore.json`。这不是 Windows/容器代码签名，Docker 镜像仍未签名。
- 原生升级服务要求宿主机安装支持 `attestation verify`、`--source-ref` 和 `--custom-trusted-root` 的 GitHub CLI，并配置 `/etc/qbot/sigstore-trusted-root.jsonl`；缺少任一项时管理台会显示自动升级不可用，不会退回到仅校验 SHA-256 的安装路径。
- GitHub Actions 使用仓库内置 `GITHUB_TOKEN`，不需要提交个人 Token。工作流不包含自动 SSH 生产部署，因为服务器地址、SSH 密钥和回滚策略尚未授权配置。
- Release 检查依赖 GitHub API；API 不可访问时应用继续运行，但不会显示最新版本。
- 原生安装由独立宿主机升级服务执行，普通网页进程不持有任意 shell / root 执行入口；没有安装升级服务的部署会明确显示不可用原因。
- 远程版本低于本地版本时不会触发降级提示，避免误回滚。
