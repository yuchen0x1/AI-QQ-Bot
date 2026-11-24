# TEST_REPORT（2026-11-24 升级分支）

本记录只覆盖当前工作区的独立升级分支 `codex/upgrade-20261124`，不代表已创建 Release 或完成真实外部平台验收。

## 本地执行结果

| 状态 | 命令 | 结果 |
|---|---|---|
| PASS | `backend/.venv/Scripts/python.exe -m pytest -q` | 256 passed、1 skipped、0 failed |
| PASS | `backend/.venv/Scripts/python.exe -m ruff check app tests migrations` | All checks passed |
| PASS | `backend/.venv/Scripts/python.exe -m compileall -q app tests migrations` | exit 0 |
| PASS | `frontend/npm run build` | `vue-tsc -b && vite build`，2383 modules transformed |
| PASS | `python -m unittest discover -s scripts/tests -p 'test_*.py'` | 7 tests OK |
| PASS | `python scripts/prepare_release.py --tag v1.5.0 --notes-output <temp>` | 版本源一致，v1.5.0 notes 就绪 |
| PASS | `git diff --check` | exit 0 |

回归范围包括 AI Provider 禁用后的路由、AI 群总结账号隔离、任务 cron 更新校验、Redis 队列 ACK/NACK/死信/恢复、告警 Webhook DNS/重定向与日志脱敏、邮件 SMTP 配置、WebSocket 前端构建。

## 未执行或未验证

- Docker 实际构建与 Compose 启动：当前 Windows 工作区未安装可用 Docker CLI/daemon。
- 真实 QQ 官方机器人连接/事件/Webhook：需要生产凭据和平台白名单。
- 真实 GitHub Release 发布、Webhook 与 API：当前分支尚未合并、打标签或发布。
- 真实 AI Provider、SMTP、告警目标：当前只有隔离测试与 MockTransport，不冒充外部服务验收。
- 生产 PostgreSQL/Redis 多实例、恢复演练与升级回滚：需要目标服务器与维护窗口。

## 发布状态

当前工作区未创建 commit、未推送分支、未创建 PR、未合并 main、未创建新 Tag、未发布 GitHub Release。上述动作需要仓库维护者在 CI 与权限检查通过后按 `docs/RELEASE_CHECKLIST.md` 完成。
