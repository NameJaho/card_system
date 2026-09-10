# 线上更新手册

本文适用于使用仓库内 `docker-compose.yml` 部署的 KeyDesk 卡密系统。本次更新包含数据库结构变更，目标 schema 为 `20260910_01`。请在维护窗口执行；不要跳过数据库备份，也不要直接在生产库上使用真实用户卡密做激活测试。

## 1. 更新内容与影响

本次发布会：

- 修复密码重置、租户隔离、旧 `instanceKey` 校验和授权状态绕过问题。
- 新增 `POST /api/client/v1/license/validate`，新客户端只需 `baseUrl`、`softwareId`、`version`。
- 对首次绑机使用原子更新，禁止验证时隐式换绑。
- 增加撤销卡密、显式换绑、旧实例密钥轮换、Bearer 认证和限流。
- 运行 Alembic 迁移 `20260910_01`，补齐历史数据并删除无效的 `auth_cards.private_key` 字段。
- 第一版 v1 协议为必须在线验证：`offlineGraceSeconds=0`、`leaseToken=null`。

更新过程中后端和前端会短暂重建，建议预留 10～20 分钟维护窗口。数据库迁移通常很快，实际时间取决于表大小和数据库性能。

## 2. 发布前准备

### 2.1 确认目录和当前版本

进入服务器上的项目目录，并记录当前提交：

```bash
cd /path/to/card_system
git status --short
git rev-parse HEAD
docker compose ps
```

工作区必须干净。若服务器上存在未提交修改，先备份并确认来源，不要直接覆盖。

记录以下信息到发布工单：

- 当前 Git SHA。
- 当前镜像 ID：`docker compose images`。
- 当前 `/health` 返回。
- 本次数据库备份文件名。
- 外层 TLS 终止组件（Caddy、Traefik、面板或负载均衡器）及证书状态。

### 2.2 检查磁盘和容器状态

```bash
df -h
docker compose ps
docker compose logs --tail=100 mysql
docker compose logs --tail=100 backend
```

MySQL 必须为健康状态，磁盘应同时容纳数据库备份和新镜像。

### 2.3 备份数据库

以下命令使用 MySQL 容器中已有的环境变量，不会把密码写入备份文件名：

```bash
set -o pipefail
mkdir -p backups
BACKUP_STAMP=$(date +%Y%m%d-%H%M%S)
docker compose exec -T mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers --events --default-character-set=utf8mb4 "$MYSQL_DATABASE"' | gzip > "backups/card-system-${BACKUP_STAMP}.sql.gz"
gzip -t "backups/card-system-${BACKUP_STAMP}.sql.gz"
ls -lh "backups/card-system-${BACKUP_STAMP}.sql.gz"
```

`set -o pipefail` 会让 `mysqldump` 失败时整条备份命令立即失败。将备份复制到项目目录之外或对象存储，并按现有备份制度验证可恢复性。只有命令退出码为 0、`gzip -t` 通过且文件大小合理后才能继续。

如果数据库不在当前 Compose 中，请改用数据库服务商的快照或备份工具，不要套用上述命令。

## 3. 配置生产环境变量

先用新版 `.env.example` 对照服务器 `.env`，不要用示例文件直接覆盖线上配置。至少确认：

```dotenv
CARD_ENV=production
CARD_PUBLIC_BASE_URL=https://card.ovorz.cn
CARD_CORS_ORIGINS=https://card.ovorz.cn
CARD_SECRET_KEY=<至少32位的高熵随机值>
CARD_ALLOW_DEV_RESET_LINK=false
CARD_APP_VERSION=<本次发布版本>
CARD_GIT_SHA=<本次发布Git-SHA>

CARD_DEFAULT_ADMIN_PASSWORD=<非默认且至少12位的引导密码>
MYSQL_ROOT_PASSWORD=<现有安全密码>
MYSQL_PASSWORD=<现有安全密码>

CARD_SMTP_HOST=<SMTP主机>
CARD_SMTP_PORT=587
CARD_SMTP_USER=<SMTP账号>
CARD_SMTP_PASSWORD=<SMTP密码>
CARD_SMTP_FROM=<发件地址>
CARD_SMTP_STARTTLS=true
```

注意：

- `CARD_SECRET_KEY` 变更会让现有后台登录会话失效，管理员需要重新登录。
- `CARD_DEFAULT_ADMIN_PASSWORD` 只用于初始化不存在的管理员；修改它不会自动修改数据库中已有管理员的密码。应先在旧版后台将真实管理员密码改为安全值。
- 已初始化的 MySQL 数据目录不会因为修改 `.env` 中的 `MYSQL_PASSWORD` 自动修改数据库账号密码。需要轮换时，应先用数据库管理流程执行 `ALTER USER`，再同步修改 `.env` 并重启后端。
- 生产环境禁止 `CARD_ALLOW_DEV_RESET_LINK=true`。必须配置 SMTP，否则忘记密码接口会安全地返回 503。
- 不要把真实 secret、卡密、实例密钥或数据库备份提交到 Git。

检查 Compose 配置语法：

```bash
docker compose config --quiet
```

不要把完整的 `docker compose config` 输出贴入工单，它会展开 `.env` 中的敏感值。

## 4. 获取并构建发布版本

推荐部署经过确认的提交，而不是不固定版本的分支头：

```bash
git fetch --all --tags --prune
git checkout <待发布的提交或标签>
git status --short
git rev-parse HEAD
```

确认输出的 SHA 与 `.env` 中 `CARD_GIT_SHA` 一致，然后构建新镜像：

```bash
docker compose build --pull backend frontend
docker compose images
```

此时不要删除旧镜像，回滚完成并稳定观察后再清理。

## 5. 执行数据库迁移

先确保 MySQL 正常运行：

```bash
docker compose up -d mysql
docker compose ps mysql
```

使用新后端镜像执行一次迁移：

```bash
docker compose run --rm --no-deps backend alembic upgrade head
docker compose run --rm --no-deps backend alembic current
```

预期当前版本包含：

```text
20260910_01 (head)
```

迁移会处理空值和重复的 `instance_key`，增加非空及唯一约束，并补齐安全字段。命令可重复运行；已经到达 head 时不会重复修改数据。

如果迁移失败，立即停止发布，不要启动新后端。保存完整错误日志，按第 8 节从备份恢复。

## 6. 切换服务

迁移成功后启动新后端，再启动前端：

```bash
docker compose up -d --no-deps backend
docker compose ps backend
docker compose logs --tail=200 backend

docker compose up -d --no-deps frontend
docker compose ps
```

后端容器自身也会在启动 Uvicorn 前执行 `alembic upgrade head`。显式执行第 5 节仍然有价值，因为迁移问题会在流量切换前暴露。

## 7. 发布后验收

### 7.1 健康与版本

先检查容器内链路，再检查公网 HTTPS：

```bash
curl --fail --silent --show-error http://127.0.0.1:${CARD_HTTP_PORT:-8080}/health
curl --fail --silent --show-error https://card.ovorz.cn/health
```

响应中的以下字段必须与本次发布一致：

- `status: ok`
- `schemaVersion: 20260910_01`
- `protocolVersion: v1`
- `appVersion` 为本次发布版本
- `gitSha` 为本次发布提交

同时检查外层证书：

```bash
curl --fail --show-error --head https://card.ovorz.cn/
```

公网 TLS 必须通过系统默认 CA 校验。仓库内 Nginx 只负责容器内 HTTP，证书续期仍由外层代理或面板负责。

### 7.2 无破坏协议检查

用空请求确认 v1 严格参数校验已经上线：

```bash
curl --silent --show-error \
  -H 'Content-Type: application/json' \
  -d '{}' \
  https://card.ovorz.cn/api/client/v1/license/validate
```

预期 HTTP 422，响应包含：

```json
{
  "success": false,
  "error": {
    "code": "INVALID_REQUEST",
    "retryable": false
  }
}
```

再选择一个已知软件 ID，对旧接口分别发送缺失、空和错误的 `instanceKey`。三种请求均应 `success=false` 且 `error.code=INSTANCE_KEY_INVALID`。该检查不需要真实卡密，也不会激活或换绑。

### 7.3 后台检查

使用管理员账号重新登录，确认：

- 请求使用 `Authorization: Bearer ...`，旧 `token` 请求头仅作为迁移兼容。
- 普通管理员只能看到自己租户的实例、卡密、客户、云变量、黑白名单和日志。
- 实例页面可打开“接入客户端”，复制三字段配置并下载 Python 接入包。
- 实例密钥轮换、卡密撤销和显式换绑按钮可见，但不要对生产业务卡执行测试。

### 7.4 专用测试卡验收

只有准备了专用测试实例和测试卡时才执行本节：

1. 未使用测试卡从安装 ID A 调用 v1，预期 200 且状态为 `active`。
2. 安装 ID A 再次验证，预期仍为 200。
3. 安装 ID B 验证同一张卡，预期 HTTP 409 和 `LICENSE_DEVICE_MISMATCH`，且不增加换绑次数。
4. 后台撤销测试卡，再验证，预期 HTTP 403 和 `LICENSE_REVOKED`。
5. 使用专用过期卡验证，预期 HTTP 403 和 `LICENSE_EXPIRED`。

禁止用真实业务卡做上述测试。完成后清理专用测试数据并保留脱敏验收记录。

### 7.5 日志观察

```bash
docker compose logs --since=15m mysql
docker compose logs --since=15m backend
docker compose logs --since=15m frontend
```

重点观察数据库连接、迁移失败、HTTP 5xx、SMTP、限流和 CORS 错误。日志中不应出现完整卡密、实例密钥、重置 token 或后台 token。

## 8. 回滚

### 8.1 尚未执行迁移

如果新镜像构建失败或尚未运行 `alembic upgrade head`，可直接切回发布前提交并重建：

```bash
git checkout <发布前Git-SHA>
docker compose build backend frontend
docker compose up -d --no-deps backend frontend
```

随后检查容器状态和旧版健康接口。

### 8.2 已执行迁移

本次迁移删除了历史 `private_key` 字段并补齐了实例密钥。不要仅切回旧代码，也不要把 `alembic downgrade` 当作生产数据恢复方案。正确流程是恢复发布前代码和对应数据库备份：

1. 立即停止前后端写入并保留故障日志。
2. 再次确认要恢复的备份文件、数据库名和发布前 Git SHA。
3. 停止后端和前端：`docker compose stop backend frontend`。
4. 按数据库运维流程删除并重建目标业务库，然后导入发布前的 `.sql.gz` 备份。
5. 切回发布前 Git SHA，重建并启动旧服务。
6. 验证健康接口、管理员登录和只读查询后再恢复流量。

恢复数据库会覆盖迁移后的所有新增数据，属于破坏性操作，必须由有权限的运维人员在确认备份可用、目标库准确且业务已停止写入后执行。不要从文档复制一条未核对目标的删库命令直接运行。

## 9. 发布完成标准

以下条件全部满足后才算完成：

- 所有 Compose 服务为健康或运行状态，无持续重启。
- 公网 HTTPS `/health` 可用，Git、应用、schema 和协议版本正确。
- Alembic 当前版本为 `20260910_01`。
- v1 空请求返回 422/`INVALID_REQUEST`。
- 旧协议缺失、空、错误 `instanceKey` 均被拒绝。
- 管理员租户隔离抽查通过。
- 使用专用卡完成状态机测试，或明确记录为待业务方执行。
- 观察期内没有新增 5xx、数据库迁移或 SMTP 异常。
- 数据库备份已转存，发布 SHA、镜像 ID 和验收结果已记录。

建议至少观察 30 分钟后再清理旧镜像。公网证书自动续期、到期告警和定期恢复演练属于持续运维事项，不因本次代码发布自动完成。
