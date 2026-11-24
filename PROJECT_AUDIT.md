# PROJECT_AUDIT

审计日期：2026-11-24（Asia/Shanghai）
仓库：`https://github.com/yuchen0x1/AI-QQ-Bot`
分支：`main`
HEAD：`c50e026 fix: allow license in native upgrade bundle`
基线应用版本：后端 `1.5.0`，前端 `1.5.0`（本工作区在独立升级分支上包含尚未发布的修复）

## 1. 项目定位

QBot AI 是面向 Linux 服务器的多账号 QQ 机器人管理平台。它把 QQ 官方机器人账号、群聊配置、消息/申请审核、AI 多供应商、GitHub 仓库动态通知、持久化任务、插件、邮件告警、日志、备份和在线更新放进一个 Vue 管理台。

目标用户是需要管理一个或多个官方 QQ 机器人、群通知和自动化任务的个人开发者与小型团队。生产部署路径是 Docker Compose 或 Linux 原生 Python + systemd + Nginx；本地测试支持 SQLite，生产建议 PostgreSQL + Redis。

## 2. 实际技术架构

| 层 | 实际实现 |
|---|---|
| 管理台 | Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、ECharts |
| API/运行时 | Python 3.12/3.13、FastAPI、Uvicorn、异步 SQLAlchemy 2 |
| 数据 | PostgreSQL 生产库、SQLite 测试/小型部署、Alembic 迁移 |
| 队列/广播 | Redis 可选；事件广播和 worker 入口已存在，账号连接与调度仍依赖持有运行时的 backend 进程 |
| QQ | 官方 QQ 机器人 AppID/AppSecret；Gateway WebSocket 或 Ed25519 签名 Webhook |
| 外部服务 | GitHub/Gitee API、GitHub OAuth/Webhook、AI Provider、腾讯 Agent Mail/SMTP |
| 工程交付 | Docker Compose、Nginx、systemd、GitHub Actions、原生 updater、ZIP/tar.gz 包 |
| 持久化扩展 | 受信任 Python 插件目录、配置/权限声明、插件指标与权限审计 |

## 3. 当前功能清单

- 认证：JWT 会话、HttpOnly Cookie、密码哈希、失败锁定、RBAC、TOTP、会话撤销、审计。
- 官方 QQ：多账号、WebSocket 连接、Webhook 验签、群/成员同步、消息发送、申请审核、能力声明。
- AI：Provider/模型管理、连接检查、会话、用量、fallback、群策略和后台调用限流。
- GitHub/Gitee：仓库监控、OAuth、轮询、Webhook、Release/活动通知、Markdown 卡片、失败重试、多个通知群。
- 自动化：interval/cron 任务、执行记录、重试、超时、备份、清理、健康检查。
- 运维：日志、系统状态、健康检查、备份、Redis 事件广播、在线更新面板与原生升级器。
- 扩展：插件同步/启停/绑定、插件指标、权限调用审计。
- 文档/引导：README、API、部署、安全、数据库、首次使用与邮件、GitHub 通知和更新说明。

## 4. 已核对的真实问题

### 已在本轮修复

1. `frontend/src/views/PushRulesView.vue` 用展示字段 `qq_group_display` 提交，而后端需要 `qq_group`；账号切换还会访问不存在的字段对象。
2. 前端管理台和 WebSocket 连接依赖 localStorage 中的长效 JWT，扩大 XSS 读取面；后端已经具备 HttpOnly Cookie。
3. `GiteeClient` 同时把 Token 放进 Authorization 和 URL query；URL 可能进入代理、访问日志或追踪系统。
4. Docker Uvicorn 原先使用 `--forwarded-allow-ips *`，会信任任意网络对端伪造的转发头；本轮改为 loopback literals，应用层继续用 CIDR 校验 Compose 代理客户端 IP。
5. SQLite 备份直接复制活动数据库文件，WAL 并发写入时不能保证快照一致；备份 API 还返回绝对服务器路径。
6. 原生 updater 直接解析损坏的 pointer/job JSON，可能让状态查询或升级守护进程崩溃。
7. 自动禁言把 `muted_until` 写成当前时间，数据库状态没有记录实际禁言时长。
8. GitHub 与 QQ Webhook 的后端读取路径缺少应用层 body 上限；Nginx 限制不能覆盖直连或错误代理配置。
9. 通用资源列表和仪表盘部分加载失败只留下空表/默认数字，没有明确重试入口。
10. 宣传站 favicon 是损坏的占位 URL，移动端在 640px 以下隐藏了大部分导航入口。
11. GitHub 版本检查在无关的失效 `GITHUB_TOKEN` 返回 401 时会自动匿名重试；Release 发布器改为按创建出的 release ID 上传和核对资产，并拒绝同标签重复发布。
12. 原生升级包的允许列表补充仓库 `LICENSE`，避免可安装包缺少许可证文件。
13. AI 群总结原先只按群号跨账号取消息，可能把另一机器人账号同号群的消息纳入总结；现在强制按 `account_id + group_number` 查询。
14. Redis 队列原先 `BRPOP` 取走即删除，Worker 崩溃会丢失任务；现在 processing lease、ACK/NACK、重试计数、死信队列和启动恢复均有实现与测试。
15. 告警 Webhook 只检查字面量 URL，域名可解析到私网且 HTTP 重定向可能绕过校验；现在发送前检查全部解析结果并禁用重定向，普通日志也统一脱敏。

### 仍然存在的高风险/结构性问题

- Webhook DNS 校验后到请求发送之间仍有 DNS rebinding 风险；需要固定解析结果或出站防火墙。配置态允许域名暂时解析失败以免本地测试依赖外部 DNS，实际发送仍严格校验。
- QQ 事件去重主要是进程内集合，重启或多副本可能重复落库/回复；需要数据库级事件幂等键。
- 多副本 scheduler 没有统一租约，连接绑定任务不能简单交给独立 worker；需要分布式调度锁和明确的 owner。
- WebSocket ticket 已在 `v1.5.0` 通过 `ws_tickets` 迁移持久化并一次性消费；仍需在真实多实例部署验证租约和广播边界。
- 插件是动态 Python 代码，权限上下文是约束接口而不是沙箱；不应加载不受信插件。
- Release 已增加 GitHub Actions Artifact Attestation 和原生升级前验证；SBOM、容器签名及真实主机验收仍未完成。
- Docker 基础镜像、apt 包和 Agent Mail CLI 仍未全部按 digest/lock 固定。
- Cookie 登录已经不再写入浏览器 localStorage，但登录/改密响应仍保留 `access_token` 以兼容 API 客户端；后续可增加浏览器专用不返回令牌的登录响应和 CSRF 防护。

## 5. 基线与本轮验证

| 检查 | 结果 |
|---|---|
| `backend` pytest（独立 venv） | PASS：256 passed、1 skipped、0 failed |
| `backend` Ruff（独立 venv） | PASS：`ruff check app tests migrations` |
| `backend` compileall + `prepare_release.py --tag v1.5.0` | PASS |
| `npm run build`（frontend） | PASS：vue-tsc + Vite，2383 modules transformed |
| `docker compose --env-file .env.example config --no-env-resolution --quiet` | PASS |
| `git diff --check` | PASS |
| Docker 实际构建/启动 | BLOCKED：当前主机未安装 Docker CLI |
| 真实 QQ/GitHub Webhook/AI Provider/生产 TLS | NOT RUN：需要外部凭据和服务，未以本地 mock 冒充生产验收 |

## 6. 成熟度判断

当前属于“可持续迭代的内部/小规模生产平台”，不是已经完成所有生产级证明的产品。核心业务链路、数据迁移、本地隔离测试和发布脚本较完整；生产级缺口集中在多副本一致性、事件持久化幂等、外部服务端到端证据、SBOM/容器签名和插件隔离。

## 7. 下一步重点

1. 持久化 QQ/GitHub 事件幂等键和消费状态。
2. 为 scheduler、账号租约、推送重试建立明确的多实例 owner/lease。
3. 为更新包增加签名、SBOM、依赖扫描和回滚演练。
4. 固定 SSRF DNS 解析并限制 backend 出站网络。
5. 完成真实 Docker/PostgreSQL/Redis、TLS、QQ、GitHub Webhook 和 AI Provider 验收。
6. 建立浏览器 E2E、可访问性、bundle budget 和恢复测试。
