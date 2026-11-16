# UPGRADE_ROADMAP

编制日期：2026-11-16（Asia/Shanghai）
说明：每一行都包含编号、模块、问题依据、参考实现、改进方案/效果、文件模块、难度、优先级和验收标准。`已完成`表示本轮有代码证据；`已有`表示此前已存在但本轮复核；`部分完成`表示有基础实现但仍缺生产证明；`计划`表示已确认价值但尚未实施。

| 编号 | 升级名称 / 模块 | 当前问题与依据 | 竞品参考 / 实现方式 | 改进方案与预期效果 | 文件或模块 | 难度 | 优先级 | 验收标准 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| EV-001 | 浏览器 Cookie 会话 / 认证 | localStorage 暴露长效 JWT | FastAPI 管理台常用 HttpOnly 会话 | 浏览器只走 HttpOnly Cookie，保留 Bearer API 兼容，降低 XSS 读取面 | `frontend/src/api.ts`, `router`, `App.vue` | 中 | P0 | 登录、刷新、路由守卫、登出、密码修改和 WS ticket 均只用 Cookie | 已完成 |
| EV-002 | Gitee Token URL 脱敏 / 安全 | Token 同时出现在 header 和 query | 成熟 API 客户端优先 Authorization header | 移除 query Token，避免 URL 日志泄漏 | `backend/app/services/github/provider.py` | 低 | P0 | MockTransport 断言 URL 无 Token、Authorization 保留 | 已完成 |
| EV-003 | Webhook body 上限 / 安全 | 直连 backend 可无界读取 body | Nginx 限制之外增加应用边界 | GitHub/QQ Webhook 流式读取，2 MiB 超限返回 413 | `backend/app/api/webhook.py`, `qqbot_webhook.py` | 低 | P0 | 声明长度和实际流均超限时返回 413，不进入验签/业务 | 已完成 |
| EV-004 | SQLite 一致性备份 / 数据 | 复制活动文件可能丢 WAL 一致性 | SQLite online backup API | 在线备份、临时文件、原子替换 | `backend/app/services/backup.py` | 中 | P0 | 并发写入后备份可打开，替换中断不覆盖旧备份 | 已完成 |
| EV-005 | 更新器损坏状态保护 / 更新 | pointer/job JSON 损坏会崩溃 | 原生 updater 状态机/隔离状态文件 | 校验 JSON、UUID 和 id，报告错误并阻止新安装 | `scripts/updater/daemon.py` | 低 | P0 | 损坏状态可查询、无异常泄漏、安装请求被拒绝 | 已完成 |
| EV-006 | Forwarded header 信任边界 / 部署 | Uvicorn 信任任意对端 | 反向代理只信任明确边界 | Uvicorn 只启用 loopback forwarded headers；应用层用 CIDR 校验 Compose 代理的客户端 IP | `backend/Dockerfile`, `backend/app/core/config.py` | 低 | P0 | 生成容器命令不含 `*`，应用层代理网段校验通过 | 已完成 |
| EV-007 | Release 签名与 provenance / 发布 | SHA-256 只能发现损坏，不能证明来源 | Sigstore/cosign、SLSA | 签名 manifest、OIDC provenance、容器签名 | `.github/workflows/release.yml`, `SECURITY.md` | 中 | P0 | 客户端校验签名失败即拒绝安装；Release 带 SBOM/provenance | 计划 |
| EV-008 | SSRF DNS 固定解析 / 安全 | 校验后请求时可能 DNS rebinding | 出站代理/固定解析/网络隔离 | 解析并固定目标地址，禁用不安全重定向，配合 egress ACL | `backend/app/services/alerting.py`, `core/http.py` | 高 | P0 | 公网域名重绑定到私网时请求被阻断；重定向重新校验 | 计划 |
| EV-009 | 推送规则群字段 / 核心功能 | UI 用 `qq_group_display`，API 需要 `qq_group` | 管理端表单 payload 与展示字段分离 | 用 `qq_group` 绑定，保留 display 字段只用于表格 | `frontend/src/views/PushRulesView.vue` | 低 | P1 | 新建/编辑 payload 通过后端校验，切换账号清除旧群 | 已完成 |
| EV-010 | 自动禁言到期状态 / 稳定性 | `muted_until` 被写成当前时间 | 群管理系统持久化真实动作期限 | 按 verdict.duration 写入到期时间，修复状态显示/重复管理 | `backend/app/services/bot_engine.py` | 低 | P1 | 120 秒场景剩余时间在 90~150 秒，adapter ban 仍调用 | 已完成 |
| EV-011 | 通用资源加载错误 / UX | 请求失败显示为空表，用户无法判断 | Dashboard/后台模板普遍区分 error/empty | 共享错误提示和重试入口，保留真正空状态 | `frontend/src/components/ResourceView.vue` | 低 | P1 | 断网后显示错误和重试，成功后清除错误 | 已完成 |
| EV-012 | 仪表盘失败反馈 / UX | API 失败仍显示 0 和暂无数据 | 监控面板显示故障状态 | 增加加载失败提示，静默刷新不覆盖最近成功数据 | `frontend/src/views/DashboardView.vue` | 低 | P1 | 初始请求失败可重试；静默刷新失败不清空数据 | 已完成 |
| EV-013 | QQ 事件持久化幂等 / 消息 | 去重集合只在内存，重启/多副本可重复回复 | NoneBot/事件系统通常以 event id 做幂等 | 增加来源、事件 ID、消息索引唯一键和消费状态 | `models`, `migrations`, `qq_official.py` | 高 | P1 | 相同事件跨进程/重启只落一条记录、只触发一次 AI/回复 | 计划 |
| EV-014 | GitHub delivery 幂等 / 推送 | 内存或局部记录不足以覆盖所有重复路径 | Webhook delivery ID 唯一约束 | delivery/event 唯一索引和状态机，失败可安全重试 | `services/github/monitor.py`, migrations | 中 | P1 | 同 delivery 并发到达只产生一条业务事件，失败重试不丢 | 部分完成 |
| EV-015 | Scheduler 分布式租约 / 任务 | 多 backend 可能同时跑轮询/推送 | 模板项目的 worker/调度边界与 Redis 锁 | 用 Redis/DB lease 选出唯一 scheduler owner | `services/scheduler.py`, `runtime_leases` | 高 | P1 | 两副本只执行一次，owner 故障后可接管且不双跑 | 计划 |
| EV-016 | WebSocket ticket 一次消费 / 会话 | 文档称一次性，当前只短时签名 | 短时 nonce + 一次性消费 | 票据加入 nonce，Redis/DB `SET NX` 消费，保留会话撤销检查 | `api/ws.py`, Redis | 中 | P1 | 同 ticket 第二次握手失败；多副本共享消费记录 | 计划 |
| EV-017 | AI conversation 唯一性 / AI | nullable 组合唯一约束在并发下可能重复会话 | Agent 平台使用稳定 conversation key | 使用规范化 scope key 和显式唯一列，冲突时重新读取 | `models/ai.py`, `services/ai/service.py` | 中 | P1 | 多进程同群/私聊并发只生成一条会话 | 计划 |
| EV-018 | 任务取消与超时 / 自动化 | 后台任务超时后的中止与记录需更清晰 | APScheduler/队列任务状态机 | 统一 cancellation、deadline、attempt 状态和可重入清理 | `services/scheduler.py`, `task_queue.py` | 中 | P1 | 超时有明确状态，资源释放，重启后不重复执行 | 计划 |
| EV-019 | 备份恢复演练 / 数据 | 有备份文件不等于可恢复 | Docker 模板把 backup/restore 作为验收 | 在隔离库自动恢复、校验表数/关键记录/校验和 | `scripts`, `.github/workflows` | 中 | P1 | SQLite/PostgreSQL 恢复演练通过并生成报告 | 部分完成 |
| EV-020 | 能力声明驱动 UI / 协议 | 官方 QQ 不支持的管理动作容易被误点 | NoneBot/botpy adapter capabilities | 由后端能力矩阵生成前端禁用/说明，不伪造支持 | `adapters/base.py`, views | 中 | P1 | 每个动作按 capabilities 隐藏或提示，接口仍返回明确 4xx | 部分完成 |
| EV-021 | CI pip check / Python 编译 | 依赖冲突和语法错误要早发现 | 模板项目的依赖/CI 闸门 | CI/release 增加 `pip check` 和 `compileall` | `.github/workflows/ci.yml`, `release.yml` | 低 | P2 | Actions 在测试前失败于依赖/编译问题 | 已完成 |
| EV-022 | Compose 配置校验 / 工程化 | compose 语法和插值此前只在本地检查 | 部署模板在 CI 验证配置 | CI 使用 `.env.example` 做 no-env-resolution 校验 | `.github/workflows/ci.yml`, `release.yml` | 低 | P2 | 示例配置校验通过，错误插值阻断构建 | 已完成 |
| EV-023 | PR 依赖审查 / 供应链 | CI 没有高危依赖闸门 | GitHub dependency-review | PR 使用 dependency-review-action，高危失败 | `.github/workflows/ci.yml` | 低 | P2 | 高危依赖 PR 被阻断，普通 push 不受影响 | 已完成 |
| EV-024 | Release checksum 自检 / 发布 | 生成 sums 后没有在流水线回读 | 发布流水线自验收 | `sha256sum -c` 在发布前执行 | `.github/workflows/release.yml` | 低 | P2 | 任一资产变更导致发布 job 失败 | 已完成 |
| EV-025 | ECharts 按需加载 / 性能 | 图表依赖影响首屏 | Dashboard 异步组件/现代前端拆 chunk | 保持图表异步加载并量化主 chunk | `DashboardView.vue`, Vite | 中 | P2 | 首屏不加载图表 chunk；构建报告记录大小 | 已有 |
| EV-026 | 资源页共享错误状态 / UX | 各页 catch 行为不一致 | 后台模板统一错误/空状态 | ResourceView 统一承载 retry 和空态语义 | `ResourceView.vue` | 低 | P2 | 所有使用 ResourceView 的页面获得一致提示 | 已完成 |
| EV-027 | 宣传站 favicon / 品牌 | favicon 是损坏占位 URL | 静态站点使用真实静态图标 | 新增 SVG 图标并引用稳定路径 | `website/index.html`, `website/favicon.svg` | 低 | P2 | 浏览器请求 `/favicon.svg` 返回 200 且图标可渲染 | 已完成 |
| EV-028 | 宣传站移动导航 / UX | 640px 以下隐藏主要入口 | 响应式站点保留导航可达性 | 移动端换行显示导航，不丢失功能入口 | `website/index.html` | 低 | P2 | 390px/640px 仍可访问功能、接入、部署、GitHub | 已完成 |
| EV-029 | 插件指标管理台 / 可观测性 | 后端指标已有，UI 尚未完整展示 | AstrBot/LangBot 的插件观测 | 插件页展示调用数、耗时、错误率和权限审计 | `PluginsView.vue`, `/plugins/{id}/metrics` | 中 | P2 | 可按插件查看最近窗口统计和失败样本 | 计划 |
| EV-030 | 审计日志过滤导出 / 运维 | 审计列表缺少组合筛选与导出 | 管理后台常见审计查询 | 增加用户、动作、时间、IP 筛选和脱敏导出 | `api/auth.py`, `SettingsView.vue` | 中 | P2 | 查询有上限、导出不含密钥/Token | 计划 |
| EV-031 | 推送重试可视化 / 通知 | 重试原因和剩余次数分散在记录 | TrendRadar/任务平台的 delivery 状态 | 推送记录显示分类错误、下次重试、退避和 DLQ | `PushRecordsView.vue`, notify | 中 | P2 | 模拟离线后状态可解释，恢复后可重试一次 | 计划 |
| EV-032 | 更新重启恢复 / 更新器 | 服务重启后需要继续显示结果 | 原生 updater 后台 job + 前端轮询 | 保留 pending 标记、重连轮询和回滚状态 | `UpdatePanel.vue`, `daemon.py` | 中 | P2 | 重启期间页面能恢复到 succeeded/failed/rolled_back | 已有 |
| EV-033 | 结构化日志脱敏 / 安全 | URL/query/header 形式的密钥覆盖不全 | 生产日志管道的字段级 redaction | 统一 secret/url/header 脱敏并加回归样本 | `core/logging.py`, tests | 中 | P2 | Token、Cookie、query、Authorization 均不会出现在日志 | 计划 |
| EV-034 | 备份管理界面 / 数据 | 备份 API 没有恢复前预检/校验和 | 运维模板的备份列表与恢复流程 | 展示文件大小、校验和、可读性、恢复到隔离目录 | `SystemView.vue`, backup service | 中 | P2 | UI 不暴露绝对路径，恢复前必须明确目标 | 部分完成 |
| EV-035 | Element Plus 按需组件 / 性能 | 主 chunk 约 1.15 MB | Vite/unplugin 按需引入 | 只保留实际组件 CSS/JS，设 bundle budget | `main.ts`, Vite config | 中 | P3 | 主 chunk 与 CSS 下降，构建 budget 超限失败 | 计划 |
| EV-036 | 路由 chunk budget / 性能 | 大页面 chunk 缺少量化上限 | Vue route-level code splitting | 为路由和关键 chunk 建预算与报告 | `vite.config.ts`, CI | 低 | P3 | 超预算 PR 有可读告警/失败策略 | 计划 |
| EV-037 | 可访问性自动检查 / UI | 目前主要依赖人工 smoke | 现代 Dashboard 的 axe/键盘检查 | 加登录、表格、弹窗、移动导航的 a11y smoke | `frontend`, Playwright | 中 | P3 | 关键页面无严重 axe 问题，键盘可完成主流程 | 计划 |
| EV-038 | 时区/本地化设置 / UX | 日期展示依赖浏览器默认中文格式 | 管理后台按用户/系统时区显示 | 统一后端 UTC、前端时区设置和 ISO 展示 | `core/timeutil`, frontend | 中 | P3 | 日志、任务、推送、会话时间一致且可解释 | 计划 |
| EV-039 | Cookie 会话 E2E / 测试 | 本轮只完成源码和构建验证 | 浏览器测试真实表单和会话 | Playwright 覆盖登录、刷新、登出、2FA、路由守卫 | `scripts/tests`, `.github/workflows` | 中 | P3 | 不读取 localStorage JWT，刷新后会话仍有效 | 计划 |
| EV-040 | Docker digest/SBOM/signing / 供应链 | 镜像和 CLI 版本可漂移 | SLSA、Syft/Grype、cosign | 固定 digest，生成 SBOM，扫描并签名镜像 | Dockerfiles, workflows | 高 | P3 | Release 附带 SBOM/签名，部署前可验证 | 计划 |
| EV-041 | Liveness/readiness 分离 / 部署 | health 同时承担存活和依赖就绪 | Kubernetes/Compose health 语义 | `/live` 不查依赖，`/ready` 查 DB/Redis/运行时 | `api/system.py`, nginx | 中 | P3 | 依赖故障只影响 readiness，不误杀进程 | 计划 |
| EV-042 | Prometheus 指标 / 观测 | 当前主要依赖页面和日志 | telegram-bot-template 的 metrics | 暴露请求、任务、推送、AI、连接和队列指标 | `api/metrics.py`, middleware | 中 | P3 | 无密钥指标可抓取，标签基数受控 | 计划 |
| EV-043 | Redis 共享限流 / 横向 | 登录/API 限流部分为进程内 | 分布式后台使用 Redis rate limit | 多实例共享登录、API、Webhook 限流状态 | `core/ratelimit.py`, Redis | 中 | P3 | 两副本共享计数，Redis 不可用时 fail-safe | 计划 |
| EV-044 | 插件签名/隔离 / 安全 | 动态 Python 插件不是沙箱 | Agent 平台常把插件视为独立扩展 | 签名 manifest，必要时子进程/容器隔离和资源限额 | `services/plugins.py`, packaging | 高 | P3 | 未签名/越权插件不能启用，超时可终止 | 计划 |
| EV-045 | 数据导出导入 / 运维 | 迁移和备份不等于用户可迁移 | 管理后台常提供可审计导出 | 脱敏导出设置/规则/绑定，导入前校验版本 | `api/system.py`, scripts | 高 | P3 | 导入到隔离库通过 schema/引用完整性检查 | 计划 |
| EV-046 | Provider circuit breaker / AI | 供应商连续失败会拖慢队列 | Agent 平台 fallback/限流 | 按 provider 统计错误、熔断、半开探测和成本配额 | `services/ai/service.py` | 高 | P3 | 失败供应商不阻塞其它模型，状态可见 | 计划 |
| EV-047 | Agent/MCP 权限与配额 / AI | 当前只有 Provider/模型调用 | AstrBot、LangBot、Tulpa 的工具编排方向 | 先落工具白名单、配额、审计，再做隔离/知识库/MCP | `docs/AGENT_MCP_KNOWLEDGE_DESIGN.md`, AI | 高 | P3 | 每次工具调用有 user/account/group、耗时、结果和拒绝原因 | 设计完成 |
| EV-048 | 通知死信队列 / 推送 | 失败记录与待重试记录边界需统一 | 可靠消息系统 DLQ | 超过预算进入 DLQ，可人工重放且不重复成功 | `services/github/notify.py`, models | 中 | P3 | 重放有幂等键和审计，失败原因保留 | 计划 |
| EV-049 | 事件回放 / 调试 | 线上事件难以复现 | 事件总线/Agent 平台保留 envelope | 保存脱敏 envelope，按权限回放到隔离处理器 | `core/events.py`, logs | 高 | P3 | 回放不触达真实 QQ，结果可比较 | 计划 |
| EV-050 | 更新回滚演练 / 发布 | updater 有回滚逻辑但缺持续演练 | 桌面更新器的 old/new smoke | CI/隔离主机跑旧版发现、安装、启动、回滚 | `scripts/updater`, release workflow | 高 | P3 | 旧版升级成功、启动失败自动回滚并留证据 | 部分完成 |

## 执行顺序

1. 先完成 EV-007、008、013、015、016、017、019，解决真实性、SSRF、幂等和多副本风险。
2. 再完成 EV-029、030、031、033、034、039，把已有后端能力变成可操作、可观测的管理台。
3. 最后完成 EV-035、037、040、041、042、043、044、045、046、048、049、050，并把真实外部环境验收接入发布闸门。
