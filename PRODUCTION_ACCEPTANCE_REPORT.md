# 生产环境全链路验收报告

验收日期：2026-11-24（Asia/Shanghai）

## A. 项目总体状态

- 当前版本：1.5.2（本地代码与生产运行版本一致）。
- 基线 Commit：`1ac6fb8b55ac38a025a3c3fdb839b1c777446747`。
- 正式 Release：`QBot AI v1.5.2`，Tag `v1.5.2`，Latest，5 个资产。
- 本轮产生了代码升级：是（可靠性、安全与版本通道修复，详见 D）。
- 是否发布新版本：否。本轮修复尚未合并 main，未创建 v1.5.3 Tag/Release。
- 当前工作区：基于 main，存在本轮未提交修改；远程 main 未改变。

## B. 真实环境验收

### 1. 服务器与现网状态

- 测试环境：`124.223.66.254`，Ubuntu 26.04 LTS，2 vCPU / 1.9 GB 内存 / 49 GB 磁盘。
- 连接方式：SSH 私钥（仅本机 `C:\Users\18155\.ssh\qqgengxin.pem`），用户 `ubuntu`，sudo 可用；没有把密钥写入仓库。
- 部署形态：systemd 原生部署；`qbot.service` 与 `qbot-updater.service` 均 active running；nginx 监听 80/443；uvicorn 监听 `127.0.0.1:8000`。
- 生产域名：`https://xiaoshuo.lenmo.top`；TLS 证书有效（Let's Encrypt，2026-11-13 至 2026-11-27）。
- 生产配置：`ENV=production`、`DEBUG=false`、SQLite、Redis 关闭、时区 Asia/Shanghai、更新通道 stable。
- 结论：通过。证据：SSH `systemctl status` / `ss -lntp` / `openssl s_client` 输出。

### 2. 健康检查与后端 API

- `GET /api/system/health`（经公网 HTTPS）：HTTP 200，0.048 秒，`status=ok`、`database=true`、`version=1.5.2`。
- 使用生产环境变量在服务器本地 ASGI 直连：管理员登录 200；`/api/system/health`、`/api/accounts`、`/api/logs`、`/api/tasks`、`/api/github/repos`、`/api/github/push-records`、`/api/system/info`、`/api/ai/models`、`/api/ai/providers`、`/api/system/stats` 均返回 200。
- 结论：通过。`/api/health`、`/health`、`/api/update/check` 返回 404 是路径不存在，不是后端故障；实际路径为 `/api/system/health` 与 `/api/system/update`。

### 3. 数据库、调度与业务数据

- 生产 SQLite：`/var/lib/qbot/qbot.db`，12.8 MB，alembic 版本已记录。
- 业务数据：1 个 QQ 官方账号、37 个 GitHub 仓库（34 个可用、3 个 unavailable）、147 条推送规则、347 条 Release、1168 个 GitHub 事件、2716 条推送记录、23 个 AI 模型、1 个 AI Provider。
- 定时任务：每日数据清理（03:20）和每日数据库备份（03:40）均为 enabled，最近运行成功；定时写入的 next_run_at 正确。
- 结论：通过。

### 4. QQ 官方机器人链路

- 账号：冷漠管家，`qq_official` / `official_ws`，enabled、auto_start、auto_reconnect 均为 true。
- 凭据探测：真实 AppID/AppSecret 成功换取 AccessToken，网关返回 `wss://api.sgroup.qq.com/websocket`，intents=33554432，回调模式 websocket。
- 现网连接记录：`account_connections` 为 online，有 lease owner 与心跳；11-24 出现过一次 “协议端断开连接”，随后自动重连成功。
- 群权限：读取了 6 个群的真实 bot_state，其中仅群 1 为 `allow_proactive_msg=true`，其余 5 个为 false；这解释了历史 40034105 频控/权限错误。
- 结论：凭据、网关、连接管理、群权限读取通过。未向正式用户群发送未经授权的测试消息；未执行群消息/私聊消息的实际收发验收，原因见 G。

### 5. GitHub Release 推送链路

- 生产 GitHub Token 解密后真实调用 `GET /user` 返回 200，账号 `yuchen0x1`，x-ratelimit-remaining=4181；此前 11-23 的 401 Bad credentials 已恢复。
- Webhook 事件与推送记录完整；11-23 有 2448 条推送记录，说明事件发现→渲染→投递→落库链路确实在生产运行。
- 发现并确认问题：11-23 的 4382 条 ERROR 主要来自 GitHub Token 失效时的重复同步错误（每 60 秒对 37 个仓库重复记录），属于日志洪水而非推送数据丢失。
- 结论：发现/解析/去重/投递路径有真实证据；重复推送防护由 `uq_push_rule_release`、`uq_push_rule_event` 与 dedupe_key 保证。

### 6. AI Provider 链路

- 生产配置了 1 个自定义 Provider（`api.hcnsec.cn`）与 23 个模型，默认模型 `auto`，累计 22 次调用 / 15 次错误。
- 本地全量自动化测试覆盖 AI 模型选择、失败回退、并发限额与错误统计。
- 结论：配置与调用记录已验证；未使用生产 API Key 发起真实聊天请求（避免消耗用户额度，见 G）。

### 7. Docker / Compose

- 本地 Windows 无 Docker CLI；服务器为原生 systemd 部署，无 Docker。
- 结论：本环境未执行 Docker 构建与 Compose 启动验收；不得描述为已通过。

### 8. 备份与恢复

- 生产定时任务存在且最近执行成功；备份目录 `/var/backups/qbot`。
- 未在正式数据库执行破坏性恢复/回滚演练。
- 结论：备份任务已验证，恢复与回滚未执行。

### 9. CI、Release 与版本一致性

- GitHub Actions 最近 12 次运行：main 与 PR 的 CI 均成功；v1.5.2 Release 工作流成功；v1.5.1 Release 工作流失败并被正确阻止发布。
- `python scripts/check_release_consistency.py`：6 passed、1 warning、0 error；版本源一致为 1.5.2。
- v1.5.1 Draft Release 仍存在（0 资产、无 Tag、无远程分支），`rg` 显示仅文档/测试夹具引用，未发现工作流引用。未经授权未删除。
- main 分支：Branch protection API 返回 404，Rulesets API 无规则；这是待用户授权的仓库设置项。
- 结论：通过（状态核实）；仓库保护缺失属于工程规范缺口，未擅自修改。

## C. 测试结果统计

| 类别 | 数量 / 结果 |
|---|---|
| 本地后端自动化测试 | 265 passed / 1 skipped（全量 pytest） |
| 本地静态检查 | Ruff `All checks passed!`；`git diff --check` 通过 |
| 发布一致性 | 6 passed、1 warning（未传 release JSON）、0 error |
| 真实生产 HTTP/SSH/API/TLS/DB 检查 | 通过，见 B |
| 真实 QQ 凭据/网关/群权限检查 | 通过，见 B |
| 真实群消息/私聊消息收发 | 未执行（需用户明确授权测试群） |
| 真实 AI API 调用 | 未执行（需用户提供测试用 Key/额度授权） |
| Docker Compose 全链路 | 未执行（本机和服务器均无 Docker） |
| 数据库恢复/升级/回滚破坏性演练 | 未执行（禁止在正式数据库执行） |
| 失败 / 阻塞 | 0 个测试失败；外部条件阻塞项见 G |

## D. 问题修复清单

### P1-1 Beta 更新通道错误返回稳定版

- 原因：`backend/app/services/update_checker.py` 的 beta 分支按发布时间排序后使用 `r.get("prerelease") or r.get("tag_name")`，任何非草稿 Release 都会入选；Beta 通道会退化为 Stable，甚至提示降级版本。
- 修复：beta 候选只接受 `prerelease=true`；没有预发布版时明确返回失败，不再回退到稳定版。
- 测试：`test_update_checker.py` 新增 2 项用例，覆盖“稳定版更新但 beta 不回退”“草稿 beta 不入选”。

### P1-2 GitHub 凭据失效导致错误日志洪水

- 原因：`sync_subscription` 每 60 秒对 37 个仓库重复记录相同错误。生产 24 小时内 5230 条 ERROR，其中 608 条“授权已失效”、大量 401 与动态投递频控。
- 修复：新增失败指纹去重，仅在失败结果变化时记录；凭据过期/限流降为 WARNING，UI 配置仍保留最新状态。
- 证据：生产 11-23 共 4382 条 ERROR；修复后定向回归测试验证连续 3 次相同失败只写 1 条日志。

### P1-3 AI Provider / QQ 官方 API 带凭据 SSRF

- 原因：管理员配置的 `base_url` 未校验，可指向 localhost、云元数据或内网；请求携带 API Key / QQBot Token；HTTP 客户端默认跟随重定向。
- 修复：新增 `backend/app/core/ssrf.py`，AI Provider 与 QQ 官方 API 地址在创建/更新时统一校验 HTTPS（Ollama 例外）、拒绝 userinfo/fragment、拒绝私有/回环/链路本地/保留 IP，并解析 DNS 全部结果；新增单元测试覆盖 169.254.169.254、127.0.0.1、userinfo、FTP 与 Ollama 白名单。
- 说明：安全审计建议把 `new_client` 默认 `follow_redirects` 改为 false；本轮未改全局默认值，避免影响现有第三方 Provider 跳转兼容性，留作后续 P2。

### P1-4 TOTP 二次验证限流可通过重新登录绕过

- 原因：2FA 限流 key 为 `2fa:{challenge_token}:{ip}`，每次密码正确后生成新 challenge 即获得新桶；登录成功还会清空 `failed_attempts`/`locked_until`。
- 修复：2FA 使用独立 IP 限流；失败次数与锁定时间持久化到用户表，重新登录不再重置 2FA 锁定；成功验证后清零。
- 测试：`test_auth.py` 新增用例，验证两次失败后重新登录并输入正确验证码仍返回 423。

### P2-1 文档/发布通道语义核查

- 核查：Stable 使用 GitHub `releases/latest`，天然排除 prerelease；Beta 原逻辑不排除 stable，已修复。
- v1.5.1 Draft 未删除（需要用户授权）；没有 Tag 或分支，不构成正式版本。
- 其他审计项（日志上下文脱敏、占位密钥校验、Webhook 持久化重放防护、operator 权限边界、CSRF、密码策略）已记录，未在本轮修改，见 E。

## E. 安全审计报告

### 已确认安全项

- 路由普遍使用 `Depends(require(...))`；JWT 绑定密码版本与会话 jti；GitHub 仓库资源有 owner scope 校验。
- 主要 SQL 使用 SQLAlchemy ORM，未发现字符串拼接 SQL；未发现前端 `v-html`/`innerHTML` 注入点。
- 告警 Webhook 有 SSRF 校验，升级包解压有路径穿越防护，systemd/Docker 均有降权与只读挂载。
- GitHub HMAC-SHA256 验签、QQ Ed25519 验签与时间戳窗口实现正确。

### 本轮修复风险

- P1：带凭据 SSRF（已修复）。
- P1：TOTP 限流绕过（已修复）。

### 剩余风险（未修复）

- P2：日志 `context` 与审计 `detail` 未结构化脱敏；第三方错误原文可能回显。
- P2：生产占位密钥校验不足（`replace-with-*` 可绕过当前检查）。
- P2：Webhook 重放防护依赖业务去重且 QQ 去重为进程内，重启/多副本可能重复处理。
- P2：operator 权限仍包含 `plugin:manage`/`task:manage`；插件目录可写时可获得进程内代码执行。
- P3：Cookie 为 HttpOnly + SameSite=Lax，生产 Secure；缺少 CSRF Token/Origin 校验。
- P3：密码策略仅校验长度，未检查常见弱口令。
- P2：`new_client` 默认 `follow_redirects=True`，若仅校验初始 URL 仍可能被重定向绕过；当前修复点在配置写入，未做逐跳复验。

## F. 生产部署建议

1. 保持当前 systemd 原生部署；不要在本机无 Docker 环境宣称 Compose 已验收。
2. 本轮修复需通过 PR 合并后，由现有升级流程部署；部署前创建数据库备份。
3. 更新后验证：`/api/system/health` 返回 200 且 version 仍为 1.5.2；`qbot.service` active；日志中不再持续出现 GitHub 同步 ERROR 洪水。
4. GitHub 凭据：确认 `user_github_tokens` 中 Token 有效；本轮已实测恢复为 200。
5. QQ 主动推送：仅为 `allow_proactive_msg=true` 的群开启通知规则；其他群需群主/管理员在 QQ 开放平台开启主动发送权限。
6. 恢复方案：使用每日备份或 `/api/system/backups` 对应文件，按 `restore.sh` 在隔离数据库恢复后验证，再切换流量。
7. 仓库保护：建议用户授权后启用 main Branch Protection / Ruleset，要求 CI 通过后再合并。

## G. 未完成事项（需要用户提供的最小必要信息）

- QQ 群授权：指定一个测试群与测试时间窗，用于真实群消息/私聊消息收发、去重与断线恢复验证。当前不能向正式用户群发送未经授权的测试数据。
- AI Provider 测试凭据：如确需真实 API 验收，请提供专用测试 Key 与额度上限；当前不愿消耗生产 Key 额度。
- GitHub Webhook 集成测试：需要用户指定一个测试仓库与测试群，并授权配置 Webhook；现有仓库为生产监控对象，未擅自改动。
- Docker Compose：需要一台安装 Docker/Docker Compose 的 Linux 隔离环境；现有服务器为原生 systemd 部署。
- 备份恢复/升级回滚演练：需要隔离数据库副本与维护窗口；禁止在正式数据库执行破坏性测试。
- v1.5.1 Draft Release 清理：需要用户明确授权删除。
- 仓库 Branch Protection / Rulesets 修改：需要用户明确授权。

## H. GitHub 最终状态

- PR 链接：尚未创建。本轮工作区存在未提交修复，按要求先完成本地验证再提交 PR。
- 合并 Commit：无（未合并）。
- main 状态：`1ac6fb8`，与 origin/main 一致。
- CI 状态：最近 main CI（run 45348635135）success；本轮分支尚未推送，无新 CI。
- Tag：正式 `v1.5.2`；`v1.5.1` 无 Tag；未创建 v1.5.3。
- Release：Latest `QBot AI v1.5.2`，5 个资产；`v1.5.1` Draft 仍存在（0 资产）。
- 分支保护：未配置（需用户授权）。

## 备注

- 本地 `.acceptance/` 为本次验收使用的只读诊断脚本集合，不属于产品代码；环境策略阻止删除，未纳入 Git 提交范围时应通过 `.gitignore` 或手动删除处理。
- 所有凭据、Token、Cookie、密码均在输出中脱敏；未向仓库提交任何密钥。
