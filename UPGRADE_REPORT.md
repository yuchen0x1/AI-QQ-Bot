# UPGRADE_REPORT

升级批次：2026-11-19（Asia/Shanghai）
项目：QBot AI 多账号智能 QQ 机器人管理平台
分支：`main`
基线：`9dde09f`
工作区：v1.4.12 改动仍保留在本地，未提交、未推送、未发布。

## A. 竞品研究

- 实际筛选：15 个相关开源项目。
- 深度核对：AstrBot、LangBot、NoneBot2、腾讯 botpy、telegram-bot-template；同时复核 Graia/Ariadne、OlivOS、TrendRadar、LittlePaimon 等项目的定位、目录入口和许可证信息。
- 最值得借鉴：NoneBot2 的 adapter/driver/plugin 边界；AstrBot/LangBot 的插件、技能、Agent 与管理台分层；botpy 的官方 QQ 协议边界；telegram-bot-template 的 PostgreSQL/Redis/Compose/CI 交付；TrendRadar 的筛选、摘要和多渠道投递思路。
- 本项目优势：官方 QQ 接入边界、账号隔离、AI/GitHub/任务/插件/审计/迁移/更新器一体化，以及 MIT 许可和中文首次引导。
- 明显短板：持久化事件幂等、多副本调度、SBOM/容器签名、插件隔离、外部服务端到端证据和前端性能预算。
- 许可证处理：没有复制 GPL/AGPL 代码，没有引入未核验许可证的依赖；仅记录可重新实现的架构思想。

## B. 升级数量与状态

- 已建立升级点：**50 项**（EV-001 至 EV-050）。
- 本轮完成：**16 项**：EV-001~006、EV-009~012、EV-021~024、EV-027~028。
- 既有能力复核为已具备：EV-025、EV-032。
- 部分完成：EV-014、EV-019、EV-020、EV-034、EV-050，以及现有跨实例事件/插件指标基础能力。
- 设计完成但未实施：EV-047。
- 未完成计划：其余 P0/P1/P2/P3 项，原因分别是需要数据库迁移、跨进程状态、真实外部服务、生产主机或更大范围架构改动；EV-007 已有代码接入但仍缺真实 Release/主机验证、SBOM 和容器签名。

逐项名称、依据、文件、优先级、验收标准和状态见 `UPGRADE_ROADMAP.md`。

## C. 本轮代码修改

### 后端

- `backend/app/services/github/provider.py`：移除 Gitee URL query Token。
- `backend/app/services/backup.py`：SQLite online backup、临时文件原子替换、健壮 URL 路径解析、PostgreSQL dump 流式 gzip、备份列表只返回文件名。
- `backend/app/api/system.py`：备份保留数量兼容旧的裸设置值，备份响应不再泄露绝对路径。
- `backend/app/api/webhook.py`、`backend/app/api/qqbot_webhook.py`：Webhook body 声明长度和流式大小限制，超限返回 413。
- `backend/app/services/bot_engine.py`：自动禁言持久化真实 `muted_until`。
- `backend/Dockerfile`：限制 Uvicorn forwarded header 信任到 loopback；应用层继续用 CIDR 校验 Compose 代理客户端 IP。
- `scripts/updater/daemon.py`：校验 pointer/job JSON，损坏状态安全报告并阻止新安装。

### 前端与宣传站

- `frontend/src/api.ts`、`router/index.ts`、`App.vue`、`stores/status.ts`、`LoginView.vue`、`SettingsView.vue`、`UpdatePanel.vue`：浏览器使用 HttpOnly Cookie，会话守卫和更新轮询不再读取 localStorage JWT；登录页和登出流程会停止实时 ticket 重连。
- `frontend/src/views/PushRulesView.vue`：修复 `qq_group` payload 字段和账号切换联动。
- `frontend/src/components/ResourceView.vue`、`DashboardView.vue`：增加错误状态和重试。
- `website/index.html`、`website/favicon.svg`：修复 favicon，保留移动端导航入口。

### 工程化

- `.github/workflows/ci.yml`：pip check、compileall、Compose 配置校验、diff check、PR dependency review。
- `.github/workflows/release.yml`：复用 CI 的 pip check、compileall、Compose smoke，发布 SHA-256 自检和 GitHub Actions provenance。

## D. 测试结果

| 检查 | 结果 |
|---|---|
| `backend` pytest | BLOCKED：当前工作区未提供 `.venv`，系统 Python 未安装 pytest |
| `backend` Ruff | BLOCKED：当前工作区未提供 `.venv`，系统 Python 未安装 ruff |
| `backend` compileall + `prepare_release.py --tag v1.4.12` | PASS |
| `npm run build` | PASS：vue-tsc + Vite，2383 modules transformed |
| `docker compose --env-file .env.example config --no-env-resolution --quiet` | PASS |
| `git diff --check` | PASS；仅有 CRLF 转换提醒 |
| 备份专项测试 | 本次未复跑：当前工作区缺少后端测试依赖；此前记录为 3 passed，SQLite online backup 行完整性手工检查通过 |
| updater 专项测试 | 本次未复跑：当前工作区缺少后端测试依赖；此前记录为 self-update 24 项通过，损坏状态自检通过 |
| Docker 实际构建/启动 | BLOCKED：Docker Desktop Linux daemon 不可用 |
| GitHub Actions provenance 真实发布与原生主机验证 | NOT RUN：当前未创建 v1.4.12 Release，且缺生产 Linux 主机与 Sigstore 信任根 |
| 真实 QQ/GitHub Webhook/AI Provider/TLS | NOT RUN：需要外部环境和凭据 |

另有一个重要的测试基线注意事项：从仓库根目录直接运行 pytest 会绕过 `backend/pytest.ini` 的异步配置，出现夹具/插件错误；项目实际约定是在 `backend` 目录使用虚拟环境运行。本次工作区没有该虚拟环境，系统 Python 也无法从 PyPI 安装依赖，因此后端测试与 Ruff 未复跑；230 passed、1 skipped 是此前已记录的结果，不作为本次验证结论。

## E. 项目变化

### 升级前

核心业务已经可运行，拥有官方 QQ 接入、AI、GitHub、任务、插件、认证和发布能力；但浏览器长效 JWT 存在脚本读取面，推送规则存在真实字段错配，备份和 Webhook 边界还不够稳健，通用页面失败反馈不足。

### 升级后

- 管理台浏览器认证回到 HttpOnly Cookie；Bearer 继续保留给 API 客户端。
- Gitee Token、备份绝对路径和任意 forwarded header 信任等暴露面已收窄。
- 备份、Webhook、更新器和自动禁言的运行时状态更接近实际行为。
- 推送规则可以按后端契约提交目标群，资源页/仪表盘能明确反馈加载失败。
- CI/release 在测试之外增加依赖、编译、Compose、差异和校验和闸门。

### 仍然不够

本轮没有把“本地代码通过”升级成“生产端到端通过”。多副本事件幂等、分布式 scheduler、DNS rebinding、SBOM/容器签名、插件隔离、真实 Docker/QQ/GitHub/AI/TLS 和恢复演练仍需外部条件与后续批次。Cookie 会话降低了持久化 JWT 暴露面，但浏览器登录响应仍为 API 兼容保留 `access_token`，CSRF 与浏览器专用响应仍列入后续安全批次。

## F. 下一阶段验收

下一批应先完成 EV-008/013/015/016/017/019：SSRF 固定解析、QQ 事件数据库幂等、scheduler lease、一次性 WS ticket、AI conversation 唯一性和隔离恢复演练；同时补 EV-007 的真实 Release/主机验证、SBOM 和容器签名。完成后再把插件指标、审计筛选、推送 DLQ 和浏览器 E2E 纳入 CI。
