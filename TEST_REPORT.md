# TEST_REPORT

## v1.3.1 发布：2026-11-14（图表遮挡 / 空错误吐司 / 通知排版 / 群同步并发）

| 状态 | 命令或范围 | 结果 |
|---|---|---|
| PASS | 浏览器实测（生产页面 CSS 注入 + 桌面/移动截图） | 图表 X 轴日期遮挡修复、页面其他位置无重叠 |
| PASS | 浏览器实测（XHR + toast 监听器，遍历 7 个页面点击刷新） | 空错误吐司根因：`@click="load"` 事件对象误作页码 → `page=[object PointerEvent]` 422 → `ElMessage.error(数组)` 渲染空框；已修复并加固拦截器 |
| PASS | `pytest tests/test_release_message_format.py` 等通知测试（26 项） | 通知表格转纯文本、资产去噪、默认模板去重下载段 |
| BLOCKED→FIXED | CI `test_each_group_has_independent_binding_code` 首次复现群同步并发缺陷 | 启动自动同步与手动同步并发时先查后插撞 `(account_id, group_number)` 唯一约束；`sync_groups` 改 ON CONFLICT 幂等写入（SQLite/PG 双方言），新增并发回归测试 |
| PASS | `pytest -q`（backend） | **201 项通过，0 失败** |
| PASS | `prepare_release.py --tag v1.3.1`、Ruff、前端构建、Release 工作流（run 43571708804） | 全部通过；v1.3.1 含 zip / tar.gz / native.tar.gz / SHA256SUMS |
| PASS | 生产服务器 `push_default_template` 自定义模板已清除（原值备份于 `/home/ubuntu/push_default_template.backup.txt`） | 升级后通知即用新内置格式；若管理员重存自定义模板则以其为准 |

## 生产在线升级验收：2026-11-14（v1.1.0 → v1.3.0，真实宿主机）：2026-11-14（v1.1.0 → v1.3.0，真实宿主机）

| 状态 | 范围 | 结果 |
|---|---|---|
| PASS | 管理台「系统设置 → 在线更新 → 立即升级」（真实管理员操作，管理员密码不在环境变量/源码中出现） | 触发任务 `72e7521d-e8d9-48e0-95e5-7ca1ef8c77fd`，POST /api/system/update/install → Unix socket → qbot-updater 守护进程 |
| PASS | 升级任务持久化 | `/var/lib/qbot-updater/jobs/72e7521d….json/.log/.tar.gz`：status=succeeded、phase=complete、progress=100、「升级成功」；previous_release=`20261114-upgrade-entry` → new_release=`v1.3.0-72e7521d…` |
| PASS | 升级前数据库备份 | `/var/lib/qbot-updater/backups/upgrade-72e7521d….db`（1.4MB，root 独占 0600），与运行数据目录分离 |
| PASS | 实际版本 | 健康检查（本机 8000 与公网 HTTPS）均为 `{"status":"ok","database":true,"version":"1.3.0"}`；`/opt/qbot/current` 已指向 v1.3.0 release |
| PASS | 服务中断窗口 | journal 时间线：14:34:23 停止 → 14:34:25 启动 → 14:34:27 迁移确认 0011_official_only → 调度器恢复（2 自定义任务 + 25 仓库轮询 + 共 29 任务）→ 14:34:29 管理台 WebSocket 自动重连；全程约 4 秒 |
| PASS | 账号 | 「生产机器人账号」qq_official / official_ws，enabled、auto_reconnect、AppSecret/AccessToken 密文（gAAAAAB…）原样保留；uvicorn 进程与 `api.sgroup.qq.com`（175.27.5.112:443，DNS 解析核对）保持 established TLS 连接，机器人真实在线 |
| PASS | 群绑定与身份映射 | groups 13、qq_official_identities 17，与升级前一致 |
| PASS | 仓库与通知群 | github_repositories 26、github_notification_targets 4 |
| PASS | 邮件授权 | email_alerts 3 行保留，`/var/lib/qbot/agent-mail` 授权目录原样 |
| PASS | 升级入口复用性 | qbot 与 qbot-updater 双服务 active；后续版本可直接后台一键升级，无需再次 install.py |

验收备注：本次为 v1.3.0 发布后首次「从旧版本通过网页一键升级到正式版」的完整线上验收，下载（GitHub CDN 约 8 分钟）、依赖安装（约 10 分钟，国内网络）、切换与恢复均由升级器自主完成，无人工干预。过程中曾误将公钥写到另一台实验室机器（实验室机，内网地址），经主机指纹核对后确认生产机为 生产机 并完成 SSH 密钥恢复。

## 路线图收口：2026-11-14（v1.3.0 发布、跨实例广播、容器验收、插件可观测性）

| 状态 | 命令或范围 | 结果 |
|---|---|---|
| PASS | `python scripts/prepare_release.py --tag v1.3.0 --notes-output …`；pytest 185 项；Ruff；`npm run build` | 预发布检查全绿 |
| PASS | `git push origin v1.3.0` → GitHub Actions Release 工作流（run 43560479144） | 全部步骤通过，发布 [v1.3.0](https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v1.3.0) 为 Latest，附件 zip / tar.gz / native.tar.gz / SHA256SUMS |
| PASS | `pytest tests/test_event_broadcast.py`（无 Redis 环境） | 5 项通过：跨实例送达、回环去重、信封校验、坏载荷忽略、无 broker 时事件 id 存在 |
| PASS | `REDIS_TEST_URL=redis://…@127.0.0.1:16379 pytest tests/test_event_broadcast.py`（Redis 为 compose 容器经 socat 转发） | 6 项全部通过：**双进程真实 Redis 跨实例广播验收**，订阅确认（subscribe ack）后才发布 |
| PASS | `docker compose up -d`（本机 Docker Desktop 29.9.3，随机凭据 `.env`） | postgres / redis / backend / frontend / nginx 全部 healthy |
| PASS | `curl /api/system/health` | HTTP 200，`{"status":"ok","database":true,"version":"1.3.0"}` |
| PASS | 管理员登录 + `GET /api/accounts`（PostgreSQL） | 200；`information_schema` 迁移出 34 张表 |
| PASS | `docker compose --profile workers up -d worker` | worker 健康，插件加载，未开队列时空转告警符合设计 |
| PASS | 容器内广播接线 | backend 日志出现「跨实例事件广播已启用：qbot:events」与「已订阅 Redis 事件频道」 |
| PASS | `POST /api/system/backup` → 恢复演练 | 生成 `/backups/qbot-20261114-055119.sql.gz`；灌入全新 `qbot_restore_test` 库还原 34 张表 |
| PASS | `pytest tests/test_plugin_metrics.py` | 4 项通过：耗时/错误率记录、has_permission 审计（含拒绝计数）、`GET /plugins/{id}/metrics` 暴露、未登录 401 |
| PASS | 全量回归 `pytest -q`（backend） | **195 项通过，0 失败，0 错误，1 跳过**（跳过项为未设置 REDIS_TEST_URL 的可选真实 Redis 用例） |
| PASS | `ruff check app tests`；`npm run build` | All checks passed；前端无改动，构建通过 |
| BLOCKED | 生产服务器在线升级验收 | v1.3.0 已发布，但服务器 `authorized_keys` 缺失控制台绑定公钥（11-14 重装后未注入），SSH 无法登录；等待管理员用控制台网页终端补公钥后执行升级并按持久化任务/版本/账号/群绑定/邮件授权验收 |

本轮实现要点：`EventHub` 发布侧新增跨实例转发（后台任务强引用，避免 create_task 弱引用被 GC 静默丢弃）、事件 id 去重窗口、信封校验；新增 `RedisEventBroker`（订阅确认后才算就绪，断线重连）；lifespan 按 `REDIS_ENABLED` 接线；`REDIS_EVENTS_CHANNEL` 进入 `.env.example`。插件侧新增 `PluginMetrics` 与权限审计环形缓冲，`has_permission` 每次判定记录在案。新增 `docs/AGENT_MCP_KNOWLEDGE_DESIGN.md` 设计评审稿（工具权限、任务隔离、数据保留、审计、威胁模型、分阶段落地）。插件与工具仍视为受信代码，不宣称沙箱。

过程中发现并修复：`hub.publish` 后台转发任务因仅被事件循环弱引用而在 Redis IO 挂起期间被 GC；`broker.start()` 不等待 subscribe 确认导致发布早于订阅。两者均有回归测试覆盖。

## 一键升级准备：2026-11-14（v1.3.0）

- PASS：`python -m pytest -q --tb=short --junitxml=../data/native-updater-tests.xml`，185 项通过，0 失败、0 错误、0 跳过。
- PASS：Ruff 检查、前端类型检查与生产构建。
- PASS：压缩包拒绝路径穿越、链接和运行数据；正式版本下载源 / digest 校验，未知请求字段拒绝，升级请求必须登录，重复请求去重且任务串行。
- PASS：维护期暂停机器人与调度器；启动检查失败恢复原版本和数据；跨提交点恢复不覆盖已经恢复写入的数据。升级状态与维护标记持久化，备份保存在 root 专用目录。
- PASS：本机 Edge 浏览器使用响应拦截检查「立即升级」单次提交、下载进度、503 重启等待、成功自动刷新和 390px 无水平溢出；此项为受控交互检查。
- PASS：真实 Linux 主机在独立目录、受限构建用户和 systemd 沙箱内完成新虚拟环境安装，uvicorn 可运行；旧服务在准备阶段保持在线。真实 GitHub 资产二进制下载可达。
- PASS：带完整前端的 native 更新包通过真实解包及版本检查；升级入口已装到旧实例，宿主机升级服务通过 Unix socket 连接。

正式版本的线上安装结果以宿主机持久化任务、实际版本和升级后的账号、群绑定、邮件授权检查为准；上述交互模拟与独立环境准备没有作为已完成线上升级的证据。

## 发布准备：2026-11-14（v1.2.0）

- PASS：前后端、npm 锁文件及登录页版本统一为 1.2.0，README 与对应版本更新说明同步。
- PASS：`python -m pytest -q tests/test_update_checker.py --tb=short`，4 项版本比较与更新接口检查通过；本轮后端行为仅修改版本元数据。
- PASS：`npm run build`，Vue 类型检查与生产构建通过；登录页版本从包元数据读取。
- PASS：`python scripts/prepare_release.py --tag v1.2.0 --notes-output ...`，版本与更新说明校验通过；错误版本标签和预发布标签均被拒绝。
- PASS：ZIP 上传包包含正确版本、官方接入和教学资源，排除本机 `.env`、数据库与私钥；发布工作流 YAML 解析通过。

标签发布工作流将重新执行完整后端检查、前端构建及两个容器镜像构建，生成 ZIP / tar.gz / SHA256SUMS 并使用对应版本的更新说明创建正式 Release。实际远程结果以标签对应的 Actions 记录及 Release 附件为准。

## 服务器验收：2026-11-14（公网部署与迁移）

- PASS：`https://your-domain.example/api/system/health` 返回 200，数据库正常；HTTP 跳转 HTTPS，未登录访问账号 API 返回 401，`.env` 路径返回 403。
- PASS：Ubuntu 原生 Python 3.12 + systemd + Nginx 部署，后端仅监听 `127.0.0.1:8000`；qbot 设置开机启动，重启服务后机器人自动在线、邮件授权保留。
- PASS：Let’s Encrypt 证书已签发；`certbot renew --dry-run --cert-name your-domain.example --non-interactive` 模拟续期成功，续期定时器与 Nginx 重载 hook 已配置。
- PASS：迁移前停止本地机器人与调度器，使用 SQLite backup API 留存完整备份并迁移。保留 1 个账号、13 个群、17 个身份映射、26 条仓库历史记录、4 个通知群、103 条规则、63 条迁移前推送记录；当前可访问并监控仓库为 25。迁移副本仅调整生产管理员密码、登录会话和连接租约。
- PASS：QQ 开放平台已加入服务器 IPv4 白名单；4 个通知群主动权限均从真实官方 API 确认已允许，GitHub 授权和仓库同步正常。
- PASS：服务器独立完成腾讯 Agent Mail 授权，发信账号为后台设置的地址，测试邮件被发信服务接受；未将接口接受等同于最终收件箱投递。
- PASS：公网浏览器完成真实表单登录、WebSocket 状态连接、官方账号表单、多群配置、邮箱配置、3 张教学图片加载与 390px 无水平溢出检查；没有页面脚本错误。慢网初始响应下选择教学步骤保持有效，测试通过响应拦截模拟加载延迟，不修改保存的教学进度。

本轮修复教学初始加载覆盖用户已选择步骤的问题，并更新只有官方接入时的操作说明。测试脚本曾在浏览器关闭时输出临时会话令牌，已确认全部测试会话撤销，后续脚本加入脱敏与请求清理。生产密码、SSH 私钥、数据库和邮箱凭据未纳入 Git 或公开源码包。

## 最新一轮：2026-11-14（仅保留官方 QQ 接入）

| 状态 | 命令或范围 | 结果 |
|---|---|---|
| PASS | `python -m pytest -q --tb=short --junitxml=../data/official-only-tests.xml`（backend） | 169 项通过，0 失败、0 错误、0 跳过 |
| PASS | `python -m ruff check app tests migrations`（backend） | All checks passed |
| PASS | `npm run build`（frontend） | Vue 类型检查与 Vite 生产构建通过 |
| PASS | 本地 API / OpenAPI | 只接受 `qq_official`；连接模式仅 WebSocket / Webhook；旧接收与扫码接口返回 404，非官方协议创建请求返回 422 |
| PASS | Playwright / 本机 Edge，1440px / 390px | 创建与编辑表单只展示官方字段，无第三方或模拟选项、无扫码入口；两种官方回调模式正常切换，编辑密钥保持空白，无水平溢出或页面脚本错误 |
| PASS | 数据库副本迁移与本地重启 | 先备份、在副本升级 `0011_official_only`，再启动本地服务自动升级；官方账号 1、群 13、身份映射 17、通知目标 4、规则 103、推送记录 55 均保留；SQLite integrity_check 为 ok |
| PASS | 本地真实官方连接 | 重启后生产机器人账号以 `official_ws` 自动恢复在线；本轮未额外向群发送测试消息 |
| PASS | `docker compose --env-file .env.example config --no-env-resolution --quiet` | 示例配置解析通过；不读取尚未创建的部署 `.env`，不代表已构建或启动容器 |
| PASS | `python scripts/package_server.py` 与 ZIP 清单检查 | 199 个文件，旧生产接入文件均不在包中，官方适配器、迁移和 3 张教学图片存在，无本地数据库或 `.env` |

已移除 OneBot、NapCat 的生产适配器、接口、扫码组件及容器配置。模拟连接只保留为测试目录内的替身，不作为运行时适配器。升级会停用历史非官方账号及其任务、规则，保留历史数据；隔离迁移测试同时覆盖停用旧配置与保留官方凭据。本轮浏览器检查只拦截教学进度读取以避免弹窗干扰，不修改用户保存的进度；表单均取消，未创建或编辑真实账号。服务器源码包排除本机数据库和凭据，未执行服务器部署。

## 补充验证：2026-11-13（QQ 设置实图指引）

- PASS：前端类型检查与生产构建；三张用户提供的 JPG 作为本地资源打包。
- PASS：1440px / 390px 浏览器验证，教学第 3 步和相关可搜索文档展示三张图片，原图正常加载，页面无水平溢出或脚本错误。
- PASS：键盘 Enter 打开放大预览、方向键切换原图、Esc 关闭并将焦点返回图片按钮。
- 图片按「群机器人设置 → 允许主动发送消息 → 按需选择消息接收范围」排列，使用原始图片文件，未修改 QQ 设置、个人数据或后端配置。

## 最新一轮：2026-11-13（首次教学、仓库同步与失败邮件）

| 状态 | 命令或范围 | 结果 |
|---|---|---|
| PASS | `python -m pytest -q --tb=short --junitxml=../data/guides-email-sync-tests.xml`（backend） | 168 项通过，0 失败、0 错误、0 跳过 |
| PASS | `python -m ruff check app tests migrations`（backend） | All checks passed |
| PASS | `npm run build`（frontend） | Vue 类型检查、Vite 生产构建通过 |
| PASS | Playwright / 本机 Edge 浏览器 | 首次教学入口、下一步、文档搜索、邮箱输入在自动刷新后保持、仪表盘不重载更新计数；390px 无水平溢出，无页面脚本错误 |
| PASS | 真实 GitHub 同步与仪表盘 API | 已不可见仓库退出当前监控，三个数据源均为 25；历史保留 |
| PASS | 真实腾讯 Agent Mail | OAuth 授权成功，测试邮件被发信服务接受，并在收件箱按测试主题查询到 |
| PASS | 迁移与持久化 | 升级前已生成 SQLite 备份；先在副本验证 `0010_guides_email_sync`，保留 25 条原推送记录，再升级本地库；重启后邮件配置保留 |
| BLOCKED | Docker 镜像构建与 Linux 容器邮箱凭据存储 | Docker Desktop Linux daemon 未运行；未将 Dockerfile 准备、服务器 OAuth 或 Linux 持久化写为已实测 |

新增测试覆盖 SMTP 密钥加密与掩码保留、收件地址修改、无消息确认时不计为发送成功、失败日志到邮件队列、重复抑制、重试与关闭取消、最后一次发送中断后不超预算重发、修改收件配置不改投旧邮件、新手进度不伪造就绪状态、仓库不可见后暂停及恢复、清单拉取失败保留现状、Windows npm shim 解析原生 CLI。

浏览器自动刷新计数的变化使用了响应拦截（25→24）验证页面无需重载；随后恢复真实 API，并确认本地真实计数 25。邮件服务测试使用真实账号，后台单元测试使用隔离数据库与模拟邮件发送；未发送真实故障邮件制造生产错误。服务器源码包排除邮箱凭据、数据库和本机环境配置。

## 最新一轮：2026-11-13（多群通知与官方 QQ 主动推送）

| 状态 | 命令或范围 | 结果 |
|---|---|---|
| PASS | `python -m pytest -q --tb=short --junitxml=../data/github-proactive-permission-tests.xml`（backend） | 157 项通过，0 失败、0 错误、0 跳过 |
| PASS | `python -m ruff check app/adapters/qq_official.py app/services/account_manager.py app/services/github/automation.py app/services/github/notify.py app/api/github_notifications.py tests/test_qq_official.py tests/test_github_notifications.py`（backend） | All checks passed |
| PASS | `npm run build`（frontend） | Vue 类型检查和 Vite 生产构建通过 |
| PASS | `git diff --check` | 无空白错误，仅现有 LF/CRLF 提醒 |
| PASS | 官方 QQ 群授权与实际补发 | 群 123456789 的 `allow_proactive_msg` 从 false 变为 true；23 条积压通知均补发成功并获得消息 ID |
| PASS | 浏览器检查通知页面 | 真实后台展示群号、近 7 天投递计数、主动权限与检查时间；「检查群权限」调用实际官方接口 |
| PARTIAL | 未来 GitHub 动态、公网部署 | 本地轮询已运行，真实动态检测和失败后补发已确认；本轮未新建远程事件验证下一次自动投递，未部署公网 HTTPS Webhook |

修复了官方机器人主动权限诊断：群内绑定回复与主动通知分开验收，测试主动通知不使用最近一次 @ 的回复上下文；QQ 未返回消息 ID 时拒绝记为成功。账号离线时暂停自动重试，保留原始错误和剩余次数。157 项为本地隔离测试；上述实际群授权与补发为独立的真实 QQ API 证据。

## 最新一轮：2026-11-12（在线更新与主分支收敛）

| 分类 | 命令/范围 | 结果 |
|---|---|---|
| 已通过 | `backend\\.venv\\Scripts\\python.exe -m pytest -o addopts="" -q` | **141 passed** |
| 已通过 | `backend\\.venv\\Scripts\\python.exe -m ruff check app tests` | **All checks passed** |
| 已通过 | `npm run build`（frontend） | `vue-tsc -b` + Vite 生产构建成功（2328 modules transformed） |
| 已通过 | `git diff --check` | 通过（仅提示现有文件的 LF/CRLF 转换提醒） |
| 已通过 | `.github/workflows/ci.yml`、`release.yml` YAML 解析 | 通过 |
| 已核对 | Git 分支与远程 | 仅保留 `main` / `origin/main`，本地 `main` 跟踪 `origin/main`，提交 `3084919` |

本轮接入 GitHub Releases 在线更新检查、稳定/Beta 渠道、资产 HTTPS 与 SHA-256 元数据过滤、管理台更新提示，以及 `main` push/PR 与 `vMAJOR.MINOR.PATCH` 发布工作流。真实 GitHub Release、生产 Docker/PostgreSQL/Redis、代码签名和服务器自动部署仍需外部环境与凭据，未将其伪造为已通过。

## 最新一轮：2026-11-09（迁移一致性与移动端 UX）

| 分类 | 命令/范围 | 结果 |
|---|---|---|
| 已通过 | `PYTHONPATH=backend .\\backend\\.venv\\Scripts\\python.exe -m pytest -q -c backend/pytest.ini backend --disable-warnings` | **97 passed** |
| 已通过 | `ruff check backend/app backend/tests backend/migrations` | **All checks passed** |
| 已通过 | `npm --prefix frontend run build` | Vite 生产构建成功（2327 modules transformed） |
| 已通过 | `alembic check`（迁移与模型一致性） | **No new upgrade operations detected** |
| 已通过 | Chromium smoke（临时 Vite + mock API，390px / 1440px） | 仪表盘渲染、抽屉展开、路由跳转后关闭、无水平溢出 |

本轮基线发现：旧迁移链虽然在 `0006_auth_security` 标记为 head，但部分数据库缺少模型声明的 `ix_account_connections_lease_id` 唯一索引；新增 `0007_runtime_lease_index` 以幂等方式补齐，并增加迁移测试断言。

本轮前端调整移除了 Google Fonts 运行时依赖，新增移动导航抽屉、准确的 WebSocket 状态文案、键盘焦点和减少动态效果支持。浏览器 smoke 只 mock 后端 API，不代表真实登录/业务操作已完成 E2E。项目虚拟环境未安装 pip 模块，因此 `pip check` 无法执行；Python 包声明未修改。

## 历史轮次：2026-11-05（GitHub OAuth）

| 分类 | 命令/范围 | 结果 |
|---|---|---|
| 已通过 | `python -m pytest -q`（backend） | **85 passed**（新增 6 项 GitHub OAuth） |
| 已通过 | `python -m ruff check app tests migrations` | **All checks passed** |
| 已通过 | `npm run build`（frontend） | `vue-tsc -b` + Vite 生产构建成功 |
| 已通过 | `alembic check`（迁移与模型一致性） | 0005 后无差异 |
| 已通过 | 线上部署验证 | `alembic current = 0005_github_oauth`、`/api/system/health` ok、`/github` 200、OAuth 7 个端点在 OpenAPI 中可见 |

新增覆盖：OAuth App 配置读写、完整授权链路（state 签名 → code 换 Token → 绑定）、伪造/缺失 state 拒绝、Token 交换失败回跳、仓库批量导入与重复导入 skipped、按归属用户取用 Token、跨用户仓库隔离（列表隐藏 + 详情 403）、解绑保留仓库。测试用 `httpx.MockTransport` 拦截 GitHub 请求，不访问真实 GitHub。

历史记录（2026-11-03）：Windows 11，Python 3.13.12，Node/npm 环境。

## 结果总览

| 分类 | 命令/范围 | 结果 |
|---|---|---|
| 已通过 | `PYTHONPATH=backend python -m pytest -q -c backend/pytest.ini backend` | **43 passed** |
| 已通过 | `python -m ruff check backend/app backend/tests` | **All checks passed** |
| 已通过 | `npm --prefix frontend run build` | Vite 生产构建成功（2326 modules transformed） |
| 配置待外部变量 | `docker compose config --quiet`（无 `.env`） | 按设计拒绝缺少必填密码/Token |

## 后端覆盖

测试使用临时 SQLite 和 HTTP Mock，不连接真实 QQ、GitHub 或 AI：

- 认证成功/失败、JWT、RBAC、登录锁定、改密。
- Mock 账号创建、启停、重连、能力检测、群/成员同步、多账号隔离。
- BotEngine 消息落库、违禁词处置、命令权限、插件命令、申请事件解析/去重/审批/协议调用、欢迎消息。
- GitHub 仓库导入、Release、Webhook HMAC、delivery/Release 去重、稳定版过滤、失败推送和重试。
- AI Provider 掩码、连接测试、调用、用量和 fallback。
- APScheduler 任务创建/运行/记录/重试/cron 校验、备份、系统设置/日志。

`backend/pytest_out.txt` 是历史结果，其中曾有失败记录。当前源码已补充推送统计、Webhook 签名、推送规则账号、消息目标和账号更新校验测试；按当前配置重跑为 **43 passed**，历史文件未改写。

## 前端构建详情

前端类型修复已合并到当前工作树；`npm --prefix frontend run build` 已通过 `vue-tsc -b` 和 Vite 生产构建，输出 `vite v6.4.5`、`2326 modules transformed`。构建产物写入 `frontend/dist`，未提交该生成目录。

## 配置检查说明

Compose 使用 `${POSTGRES_PASSWORD:?…}`、`${REDIS_PASSWORD:?…}`、NapCat token 必填插值。未复制 `.env.example` 并填写凭据时配置检查失败是预期保护，不是数据库测试失败。未启动真实 Docker 服务、PostgreSQL、Redis、TLS、NapCat、GitHub Webhook 或 AI Provider，因此这些属于**待外部配置/未完成集成验收**。

## 复测命令

```bash
PYTHONPATH=backend python -m pytest -q -c backend/pytest.ini backend
python -m ruff check backend/app backend/tests
npm --prefix frontend ci
npm --prefix frontend run build
cp .env.example .env  # 填写所有必填值后
 docker compose config --quiet
```

审计过程中未清空、删除或恢复任何数据库。
