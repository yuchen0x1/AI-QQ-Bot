# v1.6.0 验收记录

验收日期：2026-11-25（Asia/Shanghai）。基线为 `main@ef564a6a655a9304f11e690442ae759eee58f683`、正式版 v1.5.3。本轮仅执行可靠性、安全、现有控制台和更新发布范围，没有交付 RAG、Agent 或 MCP 扩展。

## 修复与测试对应

| 范围 | 交付 | 当前行为测试 |
|---|---|---|
| 仓库隔离 | QQ 命令按账号／授权群查询、执行和返回；用户删除归档仓库并撤销凭据、规则和任务 | `test_scope_auth_regressions.py` |
| 任务授权 | 创建、更新、启用、预览及执行使用创建者当前权限；拒绝伪造内部范围和非法参数 | `test_task_repository_scope.py`、`test_task_payload_boundary.py` |
| AI 请求边界 | 发送时 DNS 验证和 IP 固定、不跟随凭据重定向；Ollama 精确本地地址白名单 | `test_ai_safety.py`、`test_security_ssrf.py` |
| AI 路由 | 已启用、明确备用授权及账号／群路由范围；跨供应商默认关闭；定时摘要保留范围 | `test_ai_safety.py` |
| OAuth／WS／Webhook | 持久单次 state、会话／浏览器绑定和 PKCE；活跃连接定期撤销；独立限流和日志采样 | `test_scope_auth_regressions.py`、`test_console_permission_boundary.py` |
| 机器人与队列 | 插件先于隐式 AI；有界公平等待／期限／取消；账号和 scheduler 租约；Redis 原子领取／回收与 Worker 恢复 | `test_runtime_recovery.py`、`test_runtime_concurrency_review.py`、`test_task_queue.py` |
| QQ inbox／会话 | 持久领取、失败重试、失权 fencing 与不确定外部结果；scope key 唯一性与历史合并 | `test_runtime_recovery.py`、`test_ai_safety.py`、`test_upgrade_data.py` |
| 插件 | 持久扩展目录、内置身份区分、导入前校验、历史路径迁移 | `test_runtime_recovery.py`、`scripts/tests/test_plugin_storage.py` |
| 备份／恢复 | 导出与压缩失败检测、临时文件、原子发布、成功后保留清理；隔离演练和维护恢复 | `test_backup_failures.py`、`test_backup_storage.py`、`test_restore_workflow.py` |
| 控制台 | 两套账号目录、迟到保护、联系人及群分页、增量／未读、模型 PUT 编辑、权限／能力门控、任务表单与预览 | `frontend/src/__tests__/console.behavior.test.ts`、`test_console_contracts.py` |
| 投递记录 | 分类错误、真实重试阈值、耗尽状态、处理建议和重推权限 | `test_push_record_guidance.py`、`test_push_rule_boundary.py`、控制台组件测试 |
| 更新发现 | 缓存隔离／并发合并、ETag、退避、过期标记、六小时延后及旧键迁移 | `test_update_checker.py`、`updateReminder.test.ts`、`UpdatePanel.test.ts` |
| 安装／回退 | 保留摘要、来源证明、展开限制、串行安装、维护闸门与失败恢复 | `test_self_update.py`、发布脚本测试 |

## 实际执行的旧基线对照

以下为执行结果，不是根据代码推测。旧源码来自 `git archive ef564a6`，没有用新实现替换旧源码；HTTP、Redis 故障及控制台 API 使用受控输入，不代表生产外部服务验证。

| 场景 | 修复前实际结果 | 修复后实际结果 |
|---|---|---|
| `/roll 1d6`，私聊与 AI 开启群聊 | 插件零回复、调度 AI | 插件一次回复、不调度隐式 AI |
| 两个 stale reclaimer 同时领取快照 | 生成两个 ready job | 仅一个 ready job；并发命令模型 |
| 首次 dequeue 抛连接异常 | Worker 一次调用后退出 | 第二次调用恢复，异常没有逃出消费循环 |
| 携凭据 AI 请求收到 metadata 重定向 | 两次请求 | 一次请求，拒绝跳转 |
| 主模型失败、候选未标记备用 | 调用未授权候选 | 仅主模型被调用 |
| 控制台七项目录／模型编辑／viewer 行为 | 相同测试 7 failed | 相同测试 7 passed |
| 更新检查 12 个并发请求 | 12 次上游访问 | 合并为一次；行为测试通过 |
| 无效 SemVer `1.2.3-01` | 被接受 | 被拒绝 |
| 任务借用其他仓库权限／伪造范围 | 7 项真实缺陷失败 | 当前范围回归通过；未将旧版无预览接口算作缺陷 |
| 未登记推送群、不可空字段 null | 错误接受或数据库异常 | 请求边界拒绝；两项旧版失败／新版通过 |

七项 UI 对照测试文件 SHA-256 为 `03FCF85EA27CCD1AA16AD4E70780EDCDF883BDEBC4927BB5599DE4A281B6CAAB`。其它回归还包括修复实施前先失败、实施后通过的用例；没有声称每个新增用例都在历史完整运行环境中复跑。

## 本地验收

| 检查 | 实际结果 |
|---|---|
| 后端全量 pytest，Python 3.13.17 | **383 passed、4 skipped**，113.78 秒 |
| 后端 Ruff、compileall、pip check | 通过 |
| Python 运行依赖 pip-audit | 44 个依赖，零已知漏洞；未使用忽略项 |
| 前端 `npm ci`、typecheck、build | 通过；生产构建 2398 modules |
| 前端行为测试 | **3 files、16 passed** |
| npm audit，阈值 low | 零漏洞 |
| 发布脚本 unittest | **57 run，56 passed、1 skipped** |
| 版本一致性／发布说明生成／diff 检查 | 通过；README 在正式发布前仍保持 v1.5.3 |
| 真实 Chromium 交互 | 隔离后端键盘登录；真实 Element Plus 下拉、四次分页取得群 201 和发送请求；模型编辑 PUT；viewer；390×844；空／错误／加载反馈；零未捕获页面异常 |
| 旧版原始检查器 | v1.4.12／v1.5.2／v1.5.3，共 **18 个受控预期行为**；保留历史版本号与源码哈希 |
| 本地 ZIP／native 打包 | 通过；检查安装器及插件迁移 helper 的实际包含情况 |

本地后端四项跳过为真实 PostgreSQL 迁移、真实 Redis 队列、真实 Redis 多进程广播以及受权限限制的历史插件目录符号链接。发布脚本的一项跳过同样是 Windows 符号链接权限。远端 CI 配置了 PostgreSQL 16 与 Redis 7，并同时提供两个现有 Redis 测试变量；是否通过以本轮实际 CI 记录为准。

浏览器消息／模型操作使用受控 HTTP 数据，未向真实 QQ 或 AI 发请求。Vue 组件测试只替换第三方 Select/Option，真实浏览器另行覆盖弹层与交互。浏览器更新到期、多标签页及 2FA 状态由组件与后端行为测试覆盖，不称作生产部署验收。

## 迁移与保留限制

执行 `0016` 至 `0018`，升级前备份完整数据库、环境配置、原 `SECRET_KEY` 与插件目录。新旧版本不得同时写入新 schema。缺少有效创建者的历史 GitHub／推送重试任务需要管理员重新授权；历史全局仓库不能反推已丢失的所有者。

原生应用包不自动替换宿主机 root updater。使用旧 daemon 前先按[更新兼容指南](UPDATE_COMPATIBILITY_2026-11-25.md)运行新 installer 预迁移插件；恢复 fallback 不能替代独立备份。真实生产 Linux/systemd 安装中断和启动回滚 **NOT RUN**。维护闸门已放行且产生新写入后，不能直接切回旧代码或自动覆盖数据库；详见[迁移与回退](MIGRATION_1.6.0.md)。

真实 QQ、真实 AI、邮件及生产 Linux 外部交付 **NOT RUN**。受信插件不是沙箱，绕过 adapter 直接产生的副作用不在 fencing 保证内；插件运行超过 inbox 租约时需人工核对。QQ 外部发送中断可能保留 `uncertain`，不承诺 exactly-once。scheduler 单 owner／接管不等于任意多副本连接和发送放置已获生产验收。

## Issues、Security 与发布闸门

2026-11-25 两次实际查询：开放 Issues、Dependabot、密钥扫描告警均为空，没有虚构回复或关闭记录。代码扫描 API 返回 `404 no analysis found`，仅表示没有分析记录，不表示没有代码安全问题。初始 Python 审计发现 Starlette 依赖问题；升级 FastAPI／Starlette 后重新审计零已知漏洞。

发布必须等本轮 PR、CI（含真实 PostgreSQL／Redis 和 Compose 备份恢复）及正式 Release 工作流通过。正式发布后再核对五项资产、SHA-256、GitHub 来源证明，并运行真实历史检查器读取正式版本。正式地址和实网矩阵随发布后记录追加；受控候选结果不是已发布证明。
