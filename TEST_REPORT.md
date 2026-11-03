# TEST_REPORT

测试日期：2026-11-03（Windows 11，Python 3.13.12，Node/npm 环境）

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