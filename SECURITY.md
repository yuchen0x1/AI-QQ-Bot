# SECURITY

## 已实现控制

- bcrypt（12 rounds）密码哈希；JWT HS256，默认有效期 720 分钟，可配置。
- 登录按用户名/IP 限速，连续失败达到阈值后锁定；API 具备进程内限流。
- RBAC 角色为 `super_admin`、`operator`、`viewer`，路由使用权限依赖；危险操作写入审计日志。
- QQ access token、AI API key、GitHub token/webhook secret 使用由 `SECRET_KEY` 派生的 Fernet 密文保存，接口只返回掩码。
- Webhook 使用 HMAC-SHA256；OneBot HTTP/WS 支持账号级 token；HTTP 响应设置 nosniff、DENY、no-referrer。
- 默认 Compose 仅发布 Nginx 回环端口，内部服务在 `qbot_internal` 网络；容器以非 root `qbot` 用户运行。
- 生产启动拒绝默认/过短 `SECRET_KEY`、默认/过短 `ADMIN_PASSWORD` 及通配 CORS。

## 当前风险与真实限制

1. **默认凭据风险**：开发默认值仍是 `SECRET_KEY=change-me...`、`ADMIN_PASSWORD` 代码默认 `admin123`；`.env.example` 已改为占位符，但生产必须显式设置随机值。首次登录后立即改密。
2. **WS 凭据风险**：前端 WebSocket 将 JWT 放在 query `token`；代理访问日志可能记录 URL。优先使用受控内网、短期 token、日志脱敏和 TLS；不要把 WS 端点裸露公网。
3. **OneBot 空 token**：`_check_token` 在账号未配置密文 token 时允许请求；生产每个账号都应配置 access token，并限制网络来源。
4. **Webhook Secret 策略**：当前实现对所有环境统一要求 Secret；仓库未配置 Secret 时返回 **409**，不会接收事件；配置 Secret 后必须通过 HMAC-SHA256 验签，签名错误返回 **401**。开发/测试如需覆盖无密钥路径，应使用专门测试替身，不应放行真实 Webhook 端点。
5. **插件权限**：插件是动态 Python 代码，虽声明 `message:reply`、`storage:config`、`ai:request`、`http:request` 并通过受限 context 调用，仍不等价于沙箱。只安装审查过的插件，不给不受信插件写权限。
6. **密钥轮换**：修改 `SECRET_KEY` 会使 JWT 和既有 Fernet 密文不可解；轮换前需制定重新加密/重新登录流程。
7. **横向扩展**：EventHub 和部分限流为进程内；账号租约已落库，但扩展前仍需验证连接接管、事件广播和共享限流。

## 生产基线

使用至少 32 字符随机 `SECRET_KEY`、至少 12 字符随机管理员/数据库/Redis/NapCat 密码；`HTTP_BIND=127.0.0.1`，由外部 TLS 代理提供 HTTPS、IP allow-list、HSTS 和访问审计；不发布 PostgreSQL/Redis/6099；限制备份权限；定期更新基础镜像并在隔离环境演练恢复。