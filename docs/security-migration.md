# 安全修复迁移与发布说明

本次数据库版本为 `20260910_01`。迁移会：

- 为历史空 `instance_key` 生成独立高熵值，并增加 `NOT NULL` 与非空检查约束。
- 增加管理员 `token_version`，密码修改后使旧会话失效。
- 增加一次性密码重置 token 表（数据库只保存 SHA-256 哈希）。
- 增加 `protocol_version`、`strict_client_auth` 和安装包 `sha256` 字段。
- 补齐历史角色和卡密创建者字段。
- 删除始终等于软件 ID、从未参与认证的误导性 `auth_cards.private_key` 字段。

## 发布顺序

1. 停止写入并备份数据库，验证备份可恢复。
2. 设置生产环境变量，尤其是 `CARD_ENV=production`、`CARD_PUBLIC_BASE_URL`、`CARD_CORS_ORIGINS` 和所有 secret。
3. 在后端目录执行 `alembic upgrade head`。该命令可重复执行；已到目标版本时不会重复修改数据。
4. 启动新后端，再启动前端。仓库 Docker 镜像会在启动后端前自动执行迁移。
5. 请求 `/health`，确认 `schemaVersion=20260910_01`，并核对 `gitSha`/镜像标签。
6. 按客户端接入文档执行严格旧协议和 v1 烟雾测试，再恢复客户端发布。

```bash
cd backend
alembic upgrade head
alembic current
```

## 密码重置

生产环境必须保持 `CARD_ALLOW_DEV_RESET_LINK=false`，并配置 SMTP：

```text
CARD_SMTP_HOST=smtp.example.com
CARD_SMTP_PORT=587
CARD_SMTP_USER=mailer@example.com
CARD_SMTP_PASSWORD=<secret>
CARD_SMTP_FROM=mailer@example.com
CARD_SMTP_STARTTLS=true
```

未配置 SMTP 时，重置端点返回 503，不会回退到不安全流程。开发环境只有显式设置 `CARD_ALLOW_DEV_RESET_LINK=true` 才会在响应中返回 token。

## 生产配置门禁

`CARD_ENV=production` 时，以下情况会拒绝启动：

- `CARD_SECRET_KEY` 是默认值或少于 32 位。
- 默认管理员密码是示例值或少于 12 位。
- `CARD_PUBLIC_BASE_URL` 不是 HTTPS。
- 开启开发重置链接。
- 数据库连接仍使用仓库示例密码。

首次安全启动后应轮换管理员密码、数据库密码和签名 secret。不要把真实值写入仓库或工单。

## 回滚

应用回滚前优先恢复发布前数据库备份。迁移包含不可逆的历史空实例密钥补齐；虽然 Alembic 提供结构级 `downgrade`，它不会把生成后的密钥恢复为空（这是刻意的安全行为）。不要在生产环境直接执行 downgrade 来代替备份恢复。

## TLS 运维边界

仓库内 Nginx 仍是容器内 HTTP 反代，公网 TLS 必须由外层 Caddy、Traefik、负载均衡或面板终止。外层应启用 ACME 自动续期、每天到期检查、30/14/7 天告警、续签后 reload，并定期运行提供商对应的 dry-run。监控必须从公网使用系统 CA 请求 `https://<domain>/health`。
