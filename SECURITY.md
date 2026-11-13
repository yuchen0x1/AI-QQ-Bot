# SECURITY

## 已实现控制

- bcrypt（12 rounds）密码哈希；JWT HS256，默认有效期 720 分钟，可配置；令牌携带由密码哈希派生的版本标记，修改/重置密码后旧令牌立即失效。
- 登录按用户名/IP 限速，连续失败达到阈值后锁定；API 具备进程内限流。
- RBAC 角色为 `super_admin`、`operator`、`viewer`，路由使用权限依赖；危险操作写入审计日志。
- QQ access token、AI API key、GitHub token/webhook secret 使用由 `SECRET_KEY` 派生的 Fernet 密文保存，接口只返回掩码。
- Webhook 使用 HMAC-SHA256；QQ 官方回调使用 Ed25519 验签；HTTP 响应设置 nosniff、DENY、no-referrer。
- 系统告警 Webhook 默认拒绝 localhost、单标签主机、私有/回环/链路本地/保留 IP，降低管理端被利用为 SSRF 跳板的风险；隔离网络确需访问内网时才显式设置 `ALERT_ALLOW_PRIVATE_NETWORKS=true`。
- `/api/system/health` 在数据库不可用时返回 HTTP 503，避免容器编排把故障实例判为健康。
- 默认 Compose 仅发布 Nginx 回环端口，内部服务在 `qbot_internal` 网络；容器以非 root `qbot` 用户运行。
- 生产启动拒绝默认/过短 `SECRET_KEY`、默认/过短 `ADMIN_PASSWORD` 及通配 CORS。

## 当前风险与真实限制

1. **默认凭据风险**：开发默认值仍是 `SECRET_KEY=change-me...`、`ADMIN_PASSWORD` 代码默认 `admin123`；`.env.example` 已改为占位符，但生产必须显式设置随机值。首次登录后立即改密。
2. **WS 连接凭据**：前端状态 WebSocket 使用绑定登录会话的短期一次性票据，撤销登录会话后失效；代理仍应对连接日志脱敏并启用 TLS。
3. **官方机器人密钥**：AppSecret 加密保存；仅允许官方协议，未知或已退役协议在参数校验与运行工厂中被拒绝。密钥轮换前需保留旧密钥或完成重新授权。
4. **Webhook Secret 策略**：当前实现对所有环境统一要求 Secret；仓库未配置 Secret 时返回 **409**，不会接收事件；配置 Secret 后必须通过 HMAC-SHA256 验签，签名错误返回 **401**。开发/测试如需覆盖无密钥路径，应使用专门测试替身，不应放行真实 Webhook 端点。
5. **插件权限**：插件是动态 Python 代码，虽声明 `message:reply`、`storage:config`、`ai:request`、`http:request` 并通过受限 context 调用，仍不等价于沙箱。只安装审查过的插件，不给不受信插件写权限。
6. **密钥轮换**：修改 `SECRET_KEY` 会使 JWT 和既有 Fernet 密文不可解；轮换前需制定重新加密/重新登录流程。
7. **横向扩展**：EventHub 和部分限流为进程内；账号租约已落库，但扩展前仍需验证连接接管、事件广播和共享限流。
8. **Webhook DNS 风险**：当前校验阻断常见私网目标和 IP 字面量，但未对第三方域名做 DNS 固定/出站防火墙隔离；生产仍应限制 backend 的出站网络和可访问网段。

## 生产基线

使用至少 32 字符随机 `SECRET_KEY`、至少 12 字符随机管理员/数据库/Redis 密码；`HTTP_BIND=127.0.0.1`，由外部 TLS 代理提供 HTTPS、IP allow-list、HSTS 和访问审计；不发布 PostgreSQL/Redis；限制备份权限；定期更新基础镜像并在隔离环境演练恢复。
