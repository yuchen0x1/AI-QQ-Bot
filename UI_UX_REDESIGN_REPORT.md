# QBOT AI Control Center — 全站 UI/UX 重构报告

> 目标项目：`AI QQ 机器人`（QBot AI Control Center）
> 分支基准：`main` @ `e36098c`
> 验收日期：2026-11-24（Asia/Shanghai）
> 工作模式：后台真实 API + 真实 WebSocket，未引入任何假数据

---

## 1. 原 UI 问题分析

重构前控制台存在以下影响使用的问题：

1. **配色与品牌割裂**：各页面使用零散硬编码颜色（`#fff`、`#f0f2f5`、`#409EFF` 等），深色适配缺失，部分卡片在暗色下仍为白底。
2. **布局不统一**：页面头部、工具栏、表格、空状态各自实现，间距与圆角风格不一致。
3. **状态表达弱**：在线/离线、成功/失败、运行/等待缺少统一语义化徽章与颜色。
4. **导航与信息架构**：侧栏无分组、无搜索、无命令面板，长页面操作分散。
5. **真实数据未落到界面**：部分区域以示例/占位内容为主，无法反映真实运行状态。
6. **响应式不足**：表格与表单在平板/手机宽度下出现横向挤压或溢出。

## 2. 新设计体系

- **Design Token 化**：新增 `frontend/src/theme.ts`，集中定义 `dark` / `light` 两套语义变量（背景、表面、边框、文本、品牌、成功/警告/危险、图表配色），配合 `style.css` 全局 CSS 变量驱动。
- **主题切换**：支持「自动（跟随系统）/ 深色 / 浅色」，持久化到 `localStorage`，主题切换即时生效并同步图表（ECharts）主题。
- **统一图标体系**：新增 `AppIcon.vue`，替换零散内联 SVG/Emoji 图标。
- **统一页面骨架**：`index.html` 内早期主题脚本避免首屏闪烁；`App.vue` 提供分组侧栏、折叠、移动端 off-canvas、面包屑、顶部命令搜索、全局状态/刷新/通知/主题/语言/用户菜单、页面过渡与引导/改密弹窗。
- **命令面板**：新增 `CommandPalette.vue`，支持 `Ctrl/Cmd+K` 打开、页面跳转与常用动作，取代易误触的全局 `R` / `T` 快捷键。
- **空状态**：全部改为真实文案 + 引导操作，无假数据、无假进度动画。

## 3. 页面改造清单

| 页面 | 主要改动 |
| --- | --- |
| 仪表盘 `/` | 接入 `/api/dashboard` 真实概览、系统健康横幅、6 项统计卡、消息/AI 图表（含真实空状态）、账号状态、主机资源、异常告警、实时信号（WebSocket） |
| QQ 账号管理 `/accounts` | 真实 WebSocket 状态通道、舰队统计卡、账号列表卡片化、空状态引导 |
| 群聊管理 `/groups` | 群聊身份/策略/成员、同步群列表、危险操作二次确认、官方机器人说明 |
| 申请审核 `/requests` | 类型/状态筛选、通过/拒绝、真实空状态，保留原审批 API |
| 消息管理 `/messages` | 实时工作台（账号/会话/消息三栏）、表格/会话视图切换、方向筛选、关键词检索、分页 |
| AI 模型中心 `/ai` | Provider/模型/用量/健康状态统计、路由表、最近调用记录、Playground 入口 |
| GitHub 仓库监控 `/github` | 身份/OAuth/Token、4 项统计、通知路由（身份/群/事件范围 3 步）、运行状态、监控仓库表 |
| 推送规则 `/push-rules` | 复用 `ResourceView` 面板插槽，真实空状态与新增规则引导 |
| 推送记录 `/push-records` | 复用 `ResourceView`，状态筛选、重试入口 |
| 自动化任务 `/tasks` | 去掉重复页面标题、任务摘要卡、执行历史面板、真实任务表与操作 |
| 邮件告警 `/email` | 发信通道卡片（Agent Mail / SMTP）、收件范围、异常勾选、发信记录定时刷新 |
| 插件管理 `/plugins` | 插件运行时横幅、发现/启用/加载统计、插件列表与权限声明 |
| 系统日志 `/logs` | 级别/分类/日期筛选、展开详情、复制、上下文 JSON/堆栈、服务端脱敏说明 |
| 系统监控 `/system` | 接入 `/system/stats` 每 5 秒采样、CPU/内存/磁盘趋势图、主机/依赖/备份区 |
| 系统设置 `/settings` | 分区 rail（平台配置/账户安全/访问控制）、生命周期、告警、在线更新、登录安全/2FA、活跃会话、用户、审计 |
| 新手指引 `/help` | 6 步引导旅程（基于真实配置检查）、分步文档、常见问题 Tab |
| 登录 `/login` | `.login-shell` / `.login-visual` 双栏结构、深浅主题自适应、保留密码 + 2FA |

## 4. 组件改造清单

- `AppIcon.vue`（新增）：统一 SVG 图标集合。
- `CommandPalette.vue`（新增）：`Ctrl/Cmd+K` 命令面板，真实导航与动作。
- `theme.ts`（新增）：主题/图表配色 token。
- `index.html`：防首屏闪烁的早期主题脚本。
- `style.css`：Element Plus 变量覆盖、shell/卡片/表格/表单/弹窗/状态统一化。
- `ResourceView.vue`：令牌化表格/表单/空状态、结果计数、卡片视图能力。
- `UpdatePanel.vue`：真实 job progress/stages，移除假 100% 动画。
- `GithubNotifications.vue` / `QqSettingsIllustrations.vue`：随新视觉体系重绘。
- `i18n.ts`：补充 shell/nav 文案键。

## 5. 交互优化清单

- 页面切换过渡动画，尊重 `prefers-reduced-motion`。
- 顶部实时状态徽章 + 刷新 + 通知 + 主题 + 语言入口统一收拢。
- 表格横向滚动容器（`overflow-x: auto`）与页脚分页统一。
- 危险操作（删除、踢出、停用等）二次确认。
- 空状态均提供「下一步」引导按钮/链接。
- 命令面板可直达任意页面与常用操作。

## 6. 深浅主题验证

### 深色主题（`after/`）

| 截图 | 页面 |
| --- | --- |
| `docs/ui-redesign/screenshots/after/dashboard-dark.png` | 仪表盘 |
| `docs/ui-redesign/screenshots/after/accounts-dark.png` | QQ 账号管理 |
| `docs/ui-redesign/screenshots/after/groups-dark.png` | 群聊管理 |
| `docs/ui-redesign/screenshots/after/requests-dark.png` | 申请审核 |
| `docs/ui-redesign/screenshots/after/messages-dark.png` | 消息管理 |
| `docs/ui-redesign/screenshots/after/ai-dark.png` | AI 模型中心 |
| `docs/ui-redesign/screenshots/after/github-dark.png` | GitHub 仓库监控 |
| `docs/ui-redesign/screenshots/after/push-rules-dark.png` | 推送规则 |
| `docs/ui-redesign/screenshots/after/push-records-dark.png` | 推送记录 |
| `docs/ui-redesign/screenshots/after/tasks-dark.png` | 自动化任务 |
| `docs/ui-redesign/screenshots/after/email-dark.png` | 邮件告警 |
| `docs/ui-redesign/screenshots/after/plugins-dark.png` | 插件管理 |
| `docs/ui-redesign/screenshots/after/logs-dark.png` | 系统日志 |
| `docs/ui-redesign/screenshots/after/system-dark.png` | 系统监控 |
| `docs/ui-redesign/screenshots/after/settings-dark.png` | 系统设置 |
| `docs/ui-redesign/screenshots/after/help-dark.png` | 新手指引与文档 |
| `docs/ui-redesign/screenshots/after/login-dark.png` | 登录页 |

### 浅色主题（`light/`）

| 截图 | 页面 |
| --- | --- |
| `docs/ui-redesign/screenshots/light/dashboard-light.png` | 仪表盘 |
| `docs/ui-redesign/screenshots/light/accounts-light.png` | QQ 账号管理 |
| `docs/ui-redesign/screenshots/light/groups-light.png` | 群聊管理 |
| `docs/ui-redesign/screenshots/light/requests-light.png` | 申请审核 |
| `docs/ui-redesign/screenshots/light/messages-light.png` | 消息管理 |
| `docs/ui-redesign/screenshots/light/ai-light.png` | AI 模型中心 |
| `docs/ui-redesign/screenshots/light/github-light.png` | GitHub 仓库监控 |
| `docs/ui-redesign/screenshots/light/tasks-light.png` | 自动化任务 |
| `docs/ui-redesign/screenshots/light/email-light.png` | 邮件告警 |
| `docs/ui-redesign/screenshots/light/plugins-light.png` | 插件管理 |
| `docs/ui-redesign/screenshots/light/logs-light.png` | 系统日志 |
| `docs/ui-redesign/screenshots/light/system-light.png` | 系统监控 |
| `docs/ui-redesign/screenshots/light/settings-light.png` | 系统设置 |
| `docs/ui-redesign/screenshots/light/help-light.png` | 新手指引与文档 |
| `docs/ui-redesign/screenshots/light/login-light.png` | 登录页 |

### 改造前对比（`before/`）

`docs/ui-redesign/screenshots/before/dashboard-dark.png`、`login-dark.png`、`settings-dark.png` 保留重构前快照。

## 7. 响应式检查

- 桌面视口矩阵（320 / 375 / 480 / 768 / 834 / 1280 / 1440，含 2x HiDPI）：**0/9 存在横向溢出**。
- 全部 17 个页面在 375px（移动）与 768px（平板）下逐页扫描：**均无横向溢出**（`scrollWidth <= clientWidth`）。
- 窄屏下侧栏切换为 off-canvas，表格进入容器内横向滚动。

## 8. 构建与测试结果

### 前端生产构建

```text
cd frontend && npm run build
> vue-tsc -b && vite build   ✅
2392 modules transformed
dist/assets/index-DJVaXeCw.js   1,183.82 kB  (gzip 392.17 kB)
dist/assets/index-BJ8VEYDr.css    427.13 kB  (gzip  60.65 kB)
```

### 后端测试 / 静态检查

```text
cd backend && ..\.venv-qbot\Scripts\python.exe -m pytest -q   ✅ 全部通过
..\.venv-qbot\Scripts\python.exe -m ruff check app tests migrations   ✅ All checks passed!
..\.venv-qbot\Scripts\python.exe -m compileall -q app tests migrations   ✅
```

### 浏览器验收

- 逐页确认标题、真实数据与空状态、无横向溢出、表格滚动可用。
- 控制台错误：**0**；4xx/5xx 失败请求：**0**。
- WebSocket 遥测/状态通道建立正常；`/api/dashboard`、`/api/system/stats`、`/api/logs`、`/api/tasks` 等真实接口均返回 200。

### 静态颜色扫描

- `frontend/src` 中仅 `theme.ts`（设计 token）与 `style.css`（全局变量）保留颜色定义。
- `SettingsView.vue` 的 `.totp-qr` 使用白底 `#fff`，为 TOTP 二维码识别所必需，保留并在视觉上与深色卡片隔离。
- `DashboardView.vue` 一行 `box-shadow` 中的 `rgba` 为 ECharts tooltip 阴影，属性级、不影响主题。

## 9. 已知限制 / 未完成事项

- 2FA 绑定、密码二次确认等安全相关交互保持原有后端行为，本次仅做视觉端改造。
- 在线更新依赖 GitHub Releases/Token；未配置 Token 时可能触发限流提示（真实状态）。
- 邮件告警的 Agent Mail CLI 在纯本机环境未安装（Docker 镜像内已内置），页面如实提示。
- 高密度页面（如 GitHub 监控）在极端窄屏下以容器内横向滚动承载复杂内容。

## 10. 后续建议

- 接入 E2E（Playwright）对关键流程（登录、添加账号、创建推送规则）做回归。
- 为图表增加可访问性标签与键盘导航。
- 结合实际部署环境补充 CDN 拆分与首屏性能预算。
- 后续新增页沿用 `ResourceView` + Design Token 模式，避免重复造轮子。
