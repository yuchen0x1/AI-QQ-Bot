# TEST_REPORT（v1.5.2，2026-11-24）

本报告按「测试开始时 → 测试完成时 → 正式发布时 → 发布后核验」记录 v1.5.2。本地测试使用隔离 SQLite、HTTP/WebSocket Mock 和测试替身；Mock 结果不冒充真实 QQ、GitHub、AI、SMTP 或生产基础设施验收。

## 1. 测试开始时状态（发布前）

| 状态 | 命令 | 实际结果 |
|---|---|---|
| PASS | `backend/.venv/Scripts/python.exe -m pytest -q` | 256 passed、1 skipped、0 failed |
| PASS | `backend/.venv/Scripts/python.exe -m ruff check app tests migrations` | All checks passed |
| PASS | `backend/.venv/Scripts/python.exe -m compileall -q app tests migrations` | exit 0 |
| PASS | `frontend/npm run build` | `vue-tsc -b && vite build`，2383 modules transformed |
| PASS | `python -m unittest discover -s scripts/tests -p 'test_*.py'` | 34 tests OK（发布器 7 项 + 版本一致性 27 项） |
| PASS | `python scripts/prepare_release.py --tag v1.5.2 --notes-output <temp>` | 版本源一致，v1.5.2 canonical notes 就绪 |
| PASS | `python scripts/check_release_consistency.py --tag v1.5.2` | 7 passed、0 warning、0 error |
| PASS | `python scripts/check_release_consistency.py --release-json <latest-release.json> --require-remote` | 7 passed、0 warning、0 error |
| PASS | `git diff --check` | exit 0 |

回归范围包括 AI Provider 禁用后的路由、AI 群总结账号隔离、任务 cron/interval 更新校验、Redis 队列 ACK/NACK/死信/恢复、告警 Webhook DNS/重定向校验与日志脱敏、邮件 SMTP 配置、WebSocket 前端构建，以及新增的 README/CHANGELOG/Release/Tag/资产一致性检查。文档审计同时修正了 API 中已退役的 OneBot/mock 描述、网站对一键升级适用范围的夸大，以及 Redis 跨实例广播的过期说明。

## 2. 测试完成时状态（发布前）

- 代码升级合并提交：`5d79554`（PR #15）；版本发布提交：`180ad55`（PR #16）。
- 首次尝试 `v1.5.1` 时，后端版本仍为 `1.5.0`，Release 工作流按设计在 `package → Check release branch and versions` 失败（[run 45334849794](https://github.com/yuchen0x1/AI-QQ-Bot/actions/runs/45334849794)）；`publish` 被跳过，没有形成正式版本。
- 远程仍残留一个 `v1.5.1` **Draft Release**（ID `456350253`、0 个资产、没有对应 Tag 或远程分支）。它不是正式版本，也没有被后续流程自动删除；本报告不把“草稿”写成“已撤回”。
- 正确版本 `v1.5.2` 已同步后端、前端与锁文件版本，并补充 canonical release notes；发布前检查通过。
- 本地 Docker 实际构建/Compose 启动未执行（当前 Windows 工作区没有可用 Docker CLI/daemon）；Release 工作流中的 Compose smoke 在 CI 中成功执行。

## 3. 正式发布时状态（2026-11-24）

- Tag：`v1.5.2` → `180ad55cf5a1669f8ba3d1df18408db548773ef0`。
- Release：[QBot AI v1.5.2](https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v1.5.2)，`isDraft=false`、`isPrerelease=false`，发布时间 `2026-11-24T05:50:07Z`。
- Release 工作流：[run 45335679240](https://github.com/yuchen0x1/AI-QQ-Bot/actions/runs/45335679240) 全部成功；CI、Compose smoke、打包、SHA-256 自检、provenance 验证和按 release ID 发布均通过，依赖审查按事件类型跳过。
- 已上传 5 个资产，GitHub API 状态均为 `uploaded`：
  - `qbot-ai-1.5.2-native.tar.gz`（1,279,753 bytes）
  - `qbot-ai-1.5.2.tar.gz`（685,637 bytes）
  - `qbot-ai-1.5.2.zip`（731,825 bytes）
  - `SHA256SUMS`（265 bytes）
  - `provenance.sigstore.json`（10,972 bytes）

## 4. 发布后核验状态（2026-11-24）

- GitHub `releases/latest` 返回 `v1.5.2`，稳定标记正确，下载 URL 为 `https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v1.5.2`。
- `main` 在 Tag 之后新增一个发布验证文档提交：`a40e29d179ca4c730e085de843e0fef15e2d9e32`（仅修改 `TEST_REPORT.md` 与 `TEST_REPORT_2026-11-24.md`），没有新增代码版本变更。
- 发布后的 README 仍停留在 `v1.5.0`，已在本轮文档一致性修复中更新为 `v1.5.2` / `2026-11-24`，并同步 Release 链接和真实更新内容。
- 新增 `scripts/check_release_consistency.py`，并在 CI 中优先读取 GitHub latest Release；远端 API 不可用时只输出明确 warning，不把本地推断写成远程验证通过。
- 以下项目仍未执行真实环境验收，不能标记为通过：真实 QQ 官方机器人连接/事件/Webhook、真实 GitHub Webhook/API 写入、真实 AI Provider、SMTP/告警投递、生产 PostgreSQL/Redis 多实例、Linux Docker 主机、原生升级器回滚。

## 5. 结论

v1.5.2 是截至本报告核验时的最新正式 Release；v1.5.1 仅残留未发布的 Draft，不构成正式版本。本地自动化测试通过，外部平台与生产多实例验收仍未完成。
