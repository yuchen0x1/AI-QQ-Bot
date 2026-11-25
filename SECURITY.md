# SECURITY

## 已实现控制

- bcrypt（12 rounds）密码哈希；JWT HS256，默认有效期 720 分钟，可配置；令牌携带由密码哈希派生的版本标记，修改/重置密码后旧令牌立即失效。
- 登录按用户名/IP 限速，连续失败达到阈值后锁定；API 具备进程内限流。
- RBAC 角色为 `super_admin`、`operator`、`viewer`，路由使用权限依赖；危险操作写入审计日志。
- QQ access token、AI API key、GitHub token/webhook secret 使用由 `SECRET_KEY` 派生的 Fernet 密文保存，接口只返回掩码。
- Webhook 使用 HMAC-SHA256；QQ 官方回调使用 Ed25519 验签；HTTP 响应设置 nosniff、DENY、no-referrer。
- 系统告警 Webhook 默认拒绝 localhost、单标签主机、私有/回环/链路本地/保留 IP，降低管理端被利用为 SSRF 跳板的风险；隔离网络确需访问内网时才显式设置 `ALERT_ALLOW_PRIVATE_NETWORKS=true`。
- 告警 Webhook 发送前解析全部 A/AAAA 记录，任一结果落在私网/回环/保留地址即拒绝；实际请求不跟随重定向，避免校验后跳转到内网。SMTP/告警地址配置态允许域名暂时无法解析，真正发送仍严格校验。
- 控制台与滚动文件日志统一使用凭据脱敏 Formatter，减少 Token/密码进入文本日志的风险。
- 插件发现与加载拒绝目录、清单或 `main.py` 为符号链接的条目，并拒绝插件清单声明不受支持的权限。
- `/api/system/health` 在数据库不可用时返回 HTTP 503，避免容器编排把故障实例判为健康。
- 默认 Compose 仅发布 Nginx 回环端口，内部服务在 `qbot_internal` 网络；容器以非 root `qbot` 用户运行。
- 生产启动拒绝默认/过短 `SECRET_KEY`、默认/过短 `ADMIN_PASSWORD` 及通配 CORS。
- 管理台浏览器认证使用 HttpOnly `qbot_token` Cookie；Bearer 令牌仍保留给脚本/API 客户端，前端不再把访问令牌写入 localStorage。
- GitHub/QQ Webhook 在应用层限制请求体为 2 MiB，避免直接暴露 backend 时仅依赖 Nginx 的 body 限制。
- SQLite 备份使用 online backup 和临时文件原子替换，备份 API 只返回文件名。
- AI 请求在真正发送时校验全部 A/AAAA，连接固定到已验证 IP 并保留 Host、TLS SNI 和证书校验，拒绝凭据请求重定向。Ollama 内网访问仅接受管理员配置的精确 `OLLAMA_ALLOWED_BASE_URLS`，不豁免元数据地址。
- AI 备用模型必须启用且明确标记备用；跨供应商降级默认关闭，账号和群的模型授权范围同时约束主模型与备用模型。
- GitHub OAuth 使用持久化一次性 state、浏览器 nonce、发起 AuthSession 与 S256 PKCE；WebSocket 在持续推送期间也独立周期复查登录会话。
- Webhook 使用独立宽容限流，签名失败日志按目标聚合采样，减少无效请求造成的数据库写放大。

## 当前风险与真实限制

1. **默认凭据风险**：开发默认值仍是 `SECRET_KEY=change-me...`、`ADMIN_PASSWORD` 代码默认 `admin123`；`.env.example` 已改为占位符，但生产必须显式设置随机值。首次登录后立即改密。
2. **WS 连接凭据**：前端状态 WebSocket 使用绑定登录会话的短期签名票据，撤销登录会话后失效；票据已由数据库一次性消费保护，仍需真实多实例验收，代理应启用 TLS。
3. **官方机器人密钥**：AppSecret 加密保存；仅允许官方协议，未知或已退役协议在参数校验与运行工厂中被拒绝。密钥轮换前需保留旧密钥或完成重新授权。
4. **Webhook Secret 策略**：当前实现对所有环境统一要求 Secret；仓库未配置 Secret 时返回 **409**，不会接收事件；配置 Secret 后必须通过 HMAC-SHA256 验签，签名错误返回 **401**。开发/测试如需覆盖无密钥路径，应使用专门测试替身，不应放行真实 Webhook 端点。
5. **插件权限**：插件是动态 Python 代码，虽声明 `message:reply`、`storage:config`、`ai:request`、`http:request` 并通过受限 context 调用，仍不等价于沙箱。只安装审查过的插件，不给不受信插件写权限。
6. **密钥轮换**：修改 `SECRET_KEY` 会使 JWT 和既有 Fernet 密文不可解；轮换前需制定重新加密/重新登录流程。
7. **横向扩展**：EventHub 默认进程内，设置 `REDIS_ENABLED=true` 后可跨实例转发；部分限流仍为进程内。账号租约已落库，但扩展前仍需验证连接接管、事件广播和共享限流。
8. **出站网络边界**：AI 请求已固定连接校验后的 IP；告警 Webhook 的 DNS 校验与连接之间仍有窗口。生产仍应限制 backend 的出站网络和可访问网段，不能用 AI 的修复推断全部网络客户端已经消除 rebinding 风险。
9. **发布真实性**：Release 现在同时附带 SHA-256 校验和与 GitHub Actions Artifact Attestation；原生升级服务会在解包前校验 `provenance.sigstore.json`。当前仍没有 SBOM 或 Docker 镜像签名，容器部署不能把 SHA-256 单独当作发布者身份认证。
10. **插件执行边界**：插件目录会动态导入 Python，权限声明不是沙箱；只加载审查过的代码，后续路线包含签名 manifest 和隔离执行。
11. **历史仓库归属**：迁移保留已有 `owner_user_id=NULL` 全局仓库；旧版本已因删除用户而丢失的归属无法可靠推断，管理员应人工复核历史全局仓库。新版本删除所有者会归档并保留原归属，不继续扩大可见范围。
12. **外部副作用**：持久 inbox、任务 job ID 和成功回执减少重投，但平台请求中断后的发送结果可能不确定。`uncertain` 事件需要核对平台投递，不能把本地去重称为 QQ 平台 exactly-once。Webhook 限流与日志采样仍是进程级，多实例应另设共享入口预算。

## 生产基线

使用至少 32 字符随机 `SECRET_KEY`、至少 12 字符随机管理员/数据库/Redis 密码；`HTTP_BIND=127.0.0.1`，由外部 TLS 代理提供 HTTPS、IP allow-list、HSTS 和访问审计；不发布 PostgreSQL/Redis；限制备份权限；定期更新基础镜像并在隔离环境演练恢复。
