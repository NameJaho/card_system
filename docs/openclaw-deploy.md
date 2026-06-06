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
CARD_SECRET_KEY=替换为随机长字符串
CARD_DEFAULT_ADMIN_USER=admin
CARD_DEFAULT_ADMIN_PASSWORD=替换为强密码
CARD_DEFAULT_ADMIN_EMAIL=admin@example.com

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

## 3. 启动服务

```bash
docker compose up -d --build
```

首次启动会自动拉取 MySQL 镜像、构建后端和前端镜像、创建数据库表、初始化超级管理员与演示数据。

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

最小验证命令：

```bash
python3 clients/python/keydesk_client.py \
  --base-url http://服务器IP:8080 \
  --software-id SWxxxxxxxxxxxx \
  --auth-id KMxxxxxxxxxxxxxxxxxxxx \
  --macid DEMO-MACHINE-1 \
  verify
```

## 6. 升级项目

升级前先备份数据库。然后执行：

```bash
git pull
docker compose up -d --build
```

后端启动时会自动执行轻量表结构补齐，例如卡密创建者字段。不要手动删除 `runtime/mysql`，否则会清空全部业务数据。

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
- 后端启动失败：查看 `docker compose logs -f backend`，重点检查 `CARD_DATABASE_URL`、MySQL 密码和 MySQL 健康状态。
- 镜像拉取失败：通常是 Docker Hub 网络或镜像源问题。可以在 `.env` 中把 `PYTHON_IMAGE`、`NODE_IMAGE`、`NGINX_IMAGE`、`MYSQL_IMAGE` 改成 OpenClaw/服务器可访问镜像源里的等价镜像，然后重新执行 `docker compose up -d --build`。
- 数据丢失：确认没有执行 `rm -rf runtime/mysql`，也没有把 `MYSQL_DATA_DIR` 改到另一个目录。
- 端口冲突：修改 `.env` 里的 `CARD_HTTP_PORT`，再执行 `docker compose up -d`。
- GitHub 拉取失败：先在 OpenClaw 里配置 GitHub 访问凭据，或手动上传项目压缩包。
