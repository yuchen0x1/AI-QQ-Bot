# 竞品与相关开源项目对标

审查日期：2026-11-16（Asia/Shanghai）
项目：QBot AI 多账号智能 QQ 机器人管理平台
仓库：<https://github.com/yuchen0x1/AI-QQ-Bot>

## 研究方法与边界

本轮通过 GitHub 仓库搜索、仓库元数据、README、目录树、依赖/许可证信息和重点项目源码入口进行筛选。共筛选 15 个相关项目；对 AstrBot、LangBot、NoneBot2、botpy、telegram-bot-template 做了较深的架构/源码入口核对，其余项目完成仓库、README、许可证与定位筛选。GitHub 共享 API 对部分仓库的最新提交历史触发了速率限制，因此未把无法可靠获取的更新时间写成事实。

研究结论只用于架构取舍和路线规划，没有复制 GPL/AGPL 项目代码，也没有引入未完成许可证核查的依赖。

## 15 个研究项目

| 项目 | 许可证 | 重点能力/实际参考 | 对本项目的结论 |
|---|---|---|---|
| [AstrBot](https://github.com/AstrBotDevs/AstrBot) | AGPL-3.0 | AI Agent、多 IM、插件、Dashboard、Docker；仓库元数据显示 2026-11-16 仍有提交 | 学习插件生命周期、Agent 与管理端边界；不直接移植 AGPL 代码 |
| [LangBot](https://github.com/langbot-app/LangBot) | AGPL-3.0 | 多 IM Agent、插件、技能、Web 管理端、任务编排 | 学习平台/插件/技能分层和任务可观测性；先做权限与隔离 |
| [NoneBot2](https://github.com/nonebot/nonebot2) | MIT | driver、adapter、plugin 解耦，异步事件模型 | 保持官方 QQ adapter 与 bot engine 边界，能力按协议声明 |
| [botpy](https://github.com/tencent-connect/botpy) | MIT | QQ 官方机器人 Gateway、事件、API、示例和测试 | 作为官方 QQ 协议边界参考，不恢复个人 QQ 模拟登录 |
| [Ariadne](https://github.com/GraiaProject/Ariadne) | AGPL-3.0 | QQ 自动化、事件和消息抽象 | 借鉴事件模型与扩展边界，不复制实现 |
| [LittlePaimon](https://github.com/CMHopeSunshine/LittlePaimon) | GPL-3.0 | NoneBot2 插件、群管理、功能插件 | 学习群管理插件组织方式；许可证不适合直接合入 |
| [GenshinUID](https://github.com/KimigaiiWuyi/GenshinUID) | 需按仓库当前文件复核 | 多适配器插件生态和领域功能 | 参考插件配置与领域模块拆分，暂不引入代码 |
| [OlivOS](https://github.com/OlivOS-Team/OlivOS) | MIT | 跨平台互动栈、事件和适配器 | 参考多协议能力声明和事件标准化 |
| [kirara-ai](https://github.com/lss233/kirara-ai) | 需按仓库当前文件复核 | 多平台、多模态 AI Bot | 参考 Provider/平台解耦，保留本项目官方 QQ 定位 |
| [HarukaBot](https://github.com/SK-415/HarukaBot) | AGPL-3.0 | 定时推送、订阅和 NoneBot2 插件 | 学习推送任务的失败重试和订阅表达，不复制代码 |
| [Tulpa](https://github.com/fumingyang2004/Tulpa) | 需按仓库当前文件复核 | MCP 与 IM 桥接 | 仅吸收 MCP 工具权限、配额、审计的设计方向 |
| [TrendRadar](https://github.com/sansan0/TrendRadar) | GPL-3.0 | 信息聚合、AI 过滤、多渠道推送、MCP | 参考过滤、摘要、渠道投递链路；许可证不直接合入 |
| [telegram-bot-template](https://github.com/donbarbos/telegram-bot-template) | MIT | PostgreSQL、Redis、Docker、后台、Prometheus/Grafana、CI | 对照 Compose、健康检查、迁移、可观测性交付 |
| [CountBot](https://github.com/countbot-ai/CountBot) | 需按仓库当前文件复核 | Agent 与多 IM 连接器 | 参考 Agent 连接器边界，先完成工具权限模型 |
| [PepperBot](https://github.com/SSmJaE/PepperBot) | 需按仓库当前文件复核 | Python Bot、插件和消息事件 | 作为轻量插件/事件实现的补充样本 |

## 对标结论

| 维度 | 参考项目共同优势 | QBot AI 当前实际情况 | 取舍 |
|---|---|---|---|
| 核心功能 | 成熟项目通常把 adapter、事件、插件、任务拆开 | 已有官方 QQ WebSocket/Webhook、账号隔离、AI、GitHub、任务和插件 | 保持现有模块边界，补持久化去重和分布式调度 |
| 用户体验 | Dashboard 有清晰的失败、重试、空状态和首次引导 | 已有六步新手指引、响应式控制台；部分通用列表此前吞掉加载错误 | 本轮补 ResourceView/Dashboard 错误重试；继续做权限可见性和移动端验收 |
| UI 设计 | 生态项目更重视插件/任务状态和可观测性 | 深色控制台、实时状态和图表已具备；主包约 1.15 MB | 保留视觉语言，下一步做 bundle budget、可访问性和按需组件 |
| 技术架构 | NoneBot/LangBot 强调可扩展边界；模板项目强调 Compose/迁移/监控一体化 | FastAPI、SQLAlchemy async、Alembic、PostgreSQL/SQLite、Redis、Vue 3 | 不更换技术栈，补跨实例租约、事件去重、共享限流 |
| 性能 | 大项目使用异步事件、按需加载、指标监控 | ECharts 已异步拆 chunk；后端有并发限制和事件广播 | 继续做前端树摇、分页查询、队列背压和指标 |
| 安全 | 成熟项目逐步加入签名、权限、审计和隔离 | JWT 会话、TOTP、RBAC、加密、限流、签名和 SSRF 基础控制已存在 | 本轮移除浏览器 localStorage JWT、Gitee URL Token、限制 Webhook 体积；签名发布/DNS rebinding 仍待完成 |
| 稳定性 | 任务重试、幂等、恢复演练和可观测性是成熟项目的共性 | 已有重试、备份、更新器、Redis 事件；QQ 去重仍主要在内存 | 优先做持久化消息去重、调度租约和恢复演练 |
| 工程化 | CI、容器、依赖审计、SBOM、签名发布较完整 | CI/release 已有测试、构建、Docker 和 SHA-256 | 本轮补 pip check、compileall、Compose 校验、依赖审查和校验和自检；签名/SBOM 待补 |

## 我们的优势与短板

**优势**：官方 QQ 接入边界明确；多账号隔离、群/消息/申请/推送记录、GitHub OAuth、AI Provider、TOTP、RBAC、审计、迁移、在线更新和中文首次引导已经形成一体化管理台；项目保持 MIT 许可和较完整的本地测试。

**短板**：跨实例调度与消息幂等还没有数据库级保证；插件仍是受信 Python 代码；更新包只有校验和没有签名证明；生产 Docker、真实 QQ/GitHub Webhook、AI Provider 和 TLS 端到端证据不能由本地测试替代；前端错误反馈和 bundle 预算仍需继续改进。

## 可借鉴技术的许可证决策

- 直接采用：MIT 项目的公开接口思想、协议文档和独立概念，重新实现并保留来源记录。
- 局部重实现：adapter/driver 解耦、任务状态机、通知重试、健康检查、插件指标和权限审计。
- 暂不采用：AGPL/GPL 项目的代码复制；未经许可证核验的依赖；需要改变官方 QQ 定位的个人账号模拟登录。
