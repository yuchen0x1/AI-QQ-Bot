# UI_DESIGN

## 产品定位

QBot AI 管理控制台面向运维人员和管理员，采用深色后台工作台风格，聚焦多 QQ 账号状态、群聊治理、AI、GitHub 推送和自动化任务。

## 页面与路由

- `/login`：登录和凭据入口。
- `/`：仪表盘、系统概览、账号/消息/任务/资源状态。
- `/accounts`：账号创建、启动/停止/重启、Mock/OneBot 模式、能力与日志。
- `/groups`、`/requests`、`/messages`：群聊设置、成员、申请审核、消息查询/发送。
- `/ai`：Provider、模型、测试、对话与用量。
- `/github`、`/push-rules`、`/push-records`：仓库、Release、推送规则和结果/重试。
- `/tasks`、`/plugins`：APScheduler 任务、执行记录、插件同步/绑定/重载。
- `/logs`、`/system`、`/settings`：日志、健康检查、备份、系统配置。

## 视觉与布局

`frontend/src/style.css` 定义深色背景、紫色主色、青绿色状态色、Element Plus 组件覆盖和响应式断点。桌面端为侧边导航 + 顶部状态栏 + 内容区；窄屏侧栏收缩为图标并调整卡片网格。字体使用 DM Sans、DM Mono、Noto Sans SC（CSS 引入 Google Fonts，离线环境应准备替代字体）。

## 交互与状态

- 路由守卫检查本地 JWT；后端仍是最终认证与 RBAC 权威。
- `useRealtimeSocket` 负责状态连接、心跳、指数重连；状态文案区分连接中、实时同步、断开和异常。
- API 401 清理本地 token 并跳转登录；其他错误显示 Element Plus 消息。
- 账号/群聊/任务等危险操作应在页面显示能力限制和后端错误，不把不支持的协议操作展示成成功。

## 当前差距

前端类型错误已在当前工作树修复，`npm --prefix frontend run build` 已通过。实时仪表盘仍主要依靠页面订阅/刷新，跨实例实时事件尚未实现。