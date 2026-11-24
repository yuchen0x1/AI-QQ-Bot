# Release Checklist

这份清单用于维护者发布稳定版本。它描述的是仓库当前的 GitHub Actions 流程，不代表已经执行过某一次发布；每次发布都应把实际命令和结果记录到 `TEST_REPORT.md` 或对应 Release 说明中。

## 发布前

- [ ] 在独立分支完成代码、迁移、测试和文档，确认工作区没有不属于本次发布的未提交修改。
- [ ] 检查 `git remote -v` 指向 `yuchen0x1/AI-QQ-Bot`，并从 `origin/main` 的最新提交创建发布变更；不要在未审查的本地分支直接打标签。
- [ ] 将 `backend/app/core/version.py`、`frontend/package.json` 和 `frontend/package-lock.json` 根包版本统一为目标 SemVer。
- [ ] 在 `docs/releases/release-notes.md` 添加同版本标题和至少一条项目符号更新；涉及数据库结构时写明迁移、备份和回滚注意事项。
- [ ] 运行本地可用检查：

  ```bash
  python -m unittest discover -s scripts/tests -p 'test_*.py'
  python scripts/check_release_consistency.py --repo yuchen0x1/AI-QQ-Bot
  cd backend && python -m pytest -q && python -m ruff check app tests migrations
  cd ../frontend && npm ci && npm audit --audit-level=high && npm run build
  cd .. && docker compose --env-file .env.example config --no-env-resolution --quiet
  ```

  发布前源码版本通常领先 README 的已发布版本，检查器只会给出 warning；如果 README 声称了尚未发布的版本，检查器会报错。外部 QQ、GitHub Webhook、AI、邮箱和生产 Docker 验收不可用时，必须标记为 `NOT RUN`，不能用 Mock 结果替代。

## 打标签与 CI

1. 合并到 `main` 并等待 `CI` 的后端、前端、Compose smoke 和依赖检查完成。
2. 在同步后的 `main` 上运行版本预检：

   ```bash
   python scripts/prepare_release.py --tag vMAJOR.MINOR.PATCH --notes-output release-notes.md
   python scripts/check_release_consistency.py --repo yuchen0x1/AI-QQ-Bot --tag vMAJOR.MINOR.PATCH
   git merge-base --is-ancestor HEAD origin/main
   ```

3. 确认标签未被占用后创建并推送标签：

   ```bash
   if git show-ref --verify --quiet refs/tags/vMAJOR.MINOR.PATCH; then
     echo 'tag already exists' >&2
     exit 1
   fi
   git tag vMAJOR.MINOR.PATCH
   git push origin vMAJOR.MINOR.PATCH
   ```

   如果仓库要求签名标签，使用项目配置的 GPG/SSH 签名参数创建标签并在发布记录中保留验证结果；否则至少检查推送后的 `git show vMAJOR.MINOR.PATCH` 指向预期提交。

4. `.github/workflows/release.yml` 会重新执行 CI，校验标签祖先关系与三处版本，运行 Compose smoke，生成源码归档、服务器 ZIP、原生升级包、`SHA256SUMS` 和 GitHub Actions provenance。发布器按新建 Release 的 ID 上传并核对每个资产，发现同标签草稿或正式 Release 时会安全停止。

## 发布后验收

- [ ] 在 Actions 中确认 `ci`、打包、SHA-256 自校验、provenance 验证和发布步骤均为成功。
- [ ] 在 GitHub Release 页面核对标签、标题、更新说明和以下资产是否齐全：
  `qbot-ai-<version>.tar.gz`、`qbot-ai-<version>.zip`、`qbot-ai-<version>-native.tar.gz`、`SHA256SUMS`、`provenance.sigstore.json`。
- [ ] 下载到隔离目录后运行 `sha256sum -c SHA256SUMS`；不要在生产目录直接覆盖文件。
- [ ] 检查 `git ls-remote --tags origin vMAJOR.MINOR.PATCH` 和 GitHub Release URL，确认标签与 Release 真实存在。
- [ ] 将实际 CI run、资产校验、未执行的外部验收和剩余风险写入 `TEST_REPORT.md`，再更新 README 的最新版本块。
- [ ] 拉取 GitHub 最新正式 Release 并执行远程一致性检查：

  ```bash
  gh api repos/yuchen0x1/AI-QQ-Bot/releases/latest > /tmp/latest-release.json
  python scripts/check_release_consistency.py \
    --repo yuchen0x1/AI-QQ-Bot \
    --release-json /tmp/latest-release.json \
    --require-remote
  ```

  `--require-remote` 会核对 Tag、`isDraft` / `isPrerelease`、发布日期、Release URL 和 5 个必需资产；GitHub API 无法访问时不要省略该参数来“通过”检查，应明确记录远程状态未验证。

## 失败恢复

- 上传或校验失败时不要再次运行创建步骤。先用 `gh release list --repo yuchen0x1/AI-QQ-Bot --limit 20` 检查同标签草稿，保留资产完整且标签正确的草稿，删除空草稿或重复草稿后再重试。
- 不要覆盖或删除已发布标签，不要强制推送 `main`，不要绕过分支保护或把失败的 CI 标记为成功。
- 数据库迁移失败时停止升级，保留升级前备份并按 `DATABASE.md` 和 `DEPLOYMENT.md` 的恢复步骤在隔离环境验证；不要用 `stamp head` 掩盖未执行的迁移。
- Windows 凭据管理器只供本机 Git 客户端使用，不会替 Linux 服务器调用 GitHub API；服务器上的 `GITHUB_TOKEN` 应单独配置并按最小权限管理。

## 权限边界

发布工作流需要仓库 Actions 的写入权限和 OIDC attestation 权限。没有合并、标签或发布权限时，只提交分支并创建 PR，等待仓库维护者完成授权操作；不得通过强制推送、删除保护规则或复用旧版本号绕过限制。
