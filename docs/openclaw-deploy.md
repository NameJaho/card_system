# OpenClaw 部署指引

本文档用于在 OpenClaw 工作区内把本项目部署到 Linux 服务器。项目使用 Docker Compose 启动三类服务：MySQL、FastAPI 后端、Nginx 前端。业务数据全部写入 MySQL，并默认持久化在宿主机项目目录的 `runtime/mysql`。

OpenClaw 自身的安装请先按官方 Docker 文档完成：<https://openclawlab.com/en/docs/install/docker/>。本文只描述在已经可用的 OpenClaw 工作区中安装本卡密系统。

## 服务器要求

- Linux 服务器，建议 2 核 CPU、2 GB 内存以上。
- Docker Engine 和 Docker Compose 插件可用。
- 服务器安全组或防火墙放行后台访问端口，默认 `8080`。
- OpenClaw 工作区可以访问 GitHub，并允许执行 Docker 命令。

## 1. 获取项目

在 OpenClaw 的终端或任务执行面板中进入你的工作目录：

```bash
git clone https://github.com/NameJaho/card_system.git
cd card_system
```

如果你是通过 OpenClaw 上传压缩包或同步目录，进入项目根目录即可。项目根目录应能看到 `docker-compose.yml`、`backend/`、`frontend/`、`docs/`。

## 2. 配置环境变量

复制示例配置：

```bash
cp .env.example .env
```

编辑 `.env`，至少修改以下值：

```text
CARD_HTTP_PORT=8080
CARD_ENV=production
CARD_PUBLIC_BASE_URL=https://card.example.com
CARD_CORS_ORIGINS=https://card.example.com
CARD_SECRET_KEY=替换为随机长字符串
CARD_DEFAULT_ADMIN_USER=admin
CARD_DEFAULT_ADMIN_PASSWORD=替换为强密码
CARD_DEFAULT_ADMIN_EMAIL=admin@example.com
CARD_LICENSE_SIGNING_KEY_FILE=/run/secrets/keydesk-license-ed25519.pem
CARD_LICENSE_SIGNING_KEY_FILE_HOST=./secrets/keydesk-license-ed25519.pem
CARD_LICENSE_SIGNING_KEY_ID=license-2026-01
CARD_LICENSE_PEPPER=替换为生成后永久保持不变的至少32位高熵值

PYTHON_IMAGE=python:3.12-slim
NODE_IMAGE=node:22-alpine
NGINX_IMAGE=nginx:1.27-alpine
MYSQL_ROOT_PASSWORD=替换为强密码
MYSQL_IMAGE=mysql:8.4
MYSQL_DATABASE=card_system
MYSQL_USER=card_user
MYSQL_PASSWORD=替换为强密码
MYSQL_DATA_DIR=./runtime/mysql
TZ=Asia/Shanghai
```

`MYSQL_DATA_DIR` 是 MySQL 的宿主机持久化目录。默认值 `./runtime/mysql` 表示数据保存在项目目录下，即使容器删除后，只要该目录不删除，数据仍然保留。

启动前生成 Ed25519 签名私钥，并把 pepper 与数据库一起纳入安全灾备：

```bash
install -d -m 700 secrets
openssl genpkey -algorithm Ed25519 -out secrets/keydesk-license-ed25519.pem
chmod 600 secrets/keydesk-license-ed25519.pem
```

`CARD_LICENSE_PEPPER` 在首次迁移后不能更换或重新生成，否则所有卡密都会变成不可查询。生产 URL 必须使用 HTTPS；公网 TLS 由 OpenClaw 外层代理、Caddy、Traefik 或负载均衡器终止。

## 3. 启动服务

```bash
docker compose up -d --build
```

首次启动会自动拉取 MySQL 镜像、构建镜像，并按“安全配置预检 → Alembic 迁移 → API”启动后端。配置或签名私钥不安全时后端会拒绝启动。

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f mysql
docker compose logs -f backend
docker compose logs -f frontend
```

健康检查：

```bash
curl http://127.0.0.1:8080/health
```

如果你在 `.env` 中改了 `CARD_HTTP_PORT`，把命令里的 `8080` 改成对应端口。

## 4. 访问后台

浏览器打开：

```text
http://服务器IP:8080
```

默认登录信息来自 `.env`：

```text
账号：CARD_DEFAULT_ADMIN_USER
密码：CARD_DEFAULT_ADMIN_PASSWORD
```

登录后建议立即进入个人资料修改密码，并确认 `.env` 中的 `CARD_SECRET_KEY` 已经不是示例值。

## 5. 客户端接入

客户端接口和管理后台使用同一个域名，路径统一为 `/api/client/*`。完整说明见 [client-integration.md](client-integration.md)。

在后台实例页下载 `keydesk-<softwareId>-python-v2.zip`。解压后使用专用测试卡验证：

```bash
pip install cryptography
python smoke_test.py
```

下载包已固化生产 HTTPS 地址与 Ed25519 公钥；不要允许客户端配置覆盖信任根。完整流程见 [client-integration.md](client-integration.md)。

## 6. 升级项目

升级前先备份并验证数据库可恢复。`20260911_02` 会移除历史明文卡密，不能靠 Alembic downgrade 回滚；不要只执行无检查的 `git pull && docker compose up`。按 [production-update.md](production-update.md) 完成 pepper、签名私钥、预检、显式迁移和烟雾测试。

普通无结构变更版本才可使用：

```bash
git pull
docker compose up -d --build
```

不要手动删除 `runtime/mysql`，否则会清空全部业务数据。

## 7. 备份与恢复

推荐使用 `mysqldump`：

```bash
mkdir -p runtime/backup
docker compose exec mysql sh -c 'mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' > runtime/backup/card_system.sql
```

恢复：

```bash
cat runtime/backup/card_system.sql | docker compose exec -T mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
```

也可以备份整个 `runtime/mysql` 目录，但恢复时必须先停止服务：

```bash
docker compose down
tar -czf runtime/mysql-backup.tgz runtime/mysql
```

## 8. 常见问题

- 页面打不开：检查 `docker compose ps`，确认 `frontend` 处于 healthy/running，并确认服务器防火墙放行 `CARD_HTTP_PORT`。
- 后端启动失败：查看 `docker compose logs -f backend`，重点检查生产配置预检、Ed25519 私钥、不可变 pepper、`CARD_DATABASE_URL`、MySQL 密码和健康状态。
- 镜像拉取失败：通常是 Docker Hub 网络或镜像源问题。可以在 `.env` 中把 `PYTHON_IMAGE`、`NODE_IMAGE`、`NGINX_IMAGE`、`MYSQL_IMAGE` 改成 OpenClaw/服务器可访问镜像源里的等价镜像，然后重新执行 `docker compose up -d --build`。
- 数据丢失：确认没有执行 `rm -rf runtime/mysql`，也没有把 `MYSQL_DATA_DIR` 改到另一个目录。
- 端口冲突：修改 `.env` 里的 `CARD_HTTP_PORT`，再执行 `docker compose up -d`。
- GitHub 拉取失败：先在 OpenClaw 里配置 GitHub 访问凭据，或手动上传项目压缩包。
