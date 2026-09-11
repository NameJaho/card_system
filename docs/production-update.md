# KeyDesk v2 线上更新手册

适用范围：使用本仓库 `docker-compose.yml` 部署的 `https://card.ovorz.cn`。本次目标数据库版本为 `20260911_02`，服务端同时提供 v1/v2，Python SDK 为 2.0.0。

这是不可逆的数据迁移：完整卡密会替换为 HMAC lookup 和不透明记录引用。必须安排维护窗口、先做可恢复备份，并在流量切换前完成迁移验证。

## 1. 本次更新内容

- 新增 `POST /api/client/v2/license/validate`。
- 使用 Ed25519 JWS 签发 30～900 秒的短期 lease。
- 每个安装使用 Ed25519 设备私钥签名，服务端绑定公钥指纹。
- 增加请求时间窗、nonce 防重放、应用层与 Nginx 限流、稳定错误码和 request ID。
- 新卡只在创建时显示一次；数据库、历史列表、CSV 和审计不再保存/返回完整卡密。
- 增加按软件实例设置最低协议、lease TTL、复验间隔及 v2 使用遥测。
- v1 暂时保留；实例切到最低协议 2 后，v1 返回 HTTP 426。

本次部署只让卡密服务和官方 SDK 具备 v2 能力，不会自动修改另一个 Joom 仓库。Joom 的全路由门禁、随机任务 ID、运行期 session token 和长任务复验仍须独立发布。

## 2. 发布前记录与备份

进入实际项目目录，确认工作区干净并记录旧版本：

```bash
cd /path/to/card_system
git status --short
git rev-parse HEAD
docker compose ps
docker compose images
curl --fail --silent --show-error https://card.ovorz.cn/health
```

服务器若有未提交修改，先确认来源并单独备份，不能直接覆盖。

备份 Compose MySQL：

```bash
set -o pipefail
install -d -m 700 backups
BACKUP_STAMP=$(date +%Y%m%d-%H%M%S)
docker compose exec -T mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers --events --default-character-set=utf8mb4 "$MYSQL_DATABASE"' | gzip > "backups/card-system-${BACKUP_STAMP}.sql.gz"
gzip -t "backups/card-system-${BACKUP_STAMP}.sql.gz"
ls -lh "backups/card-system-${BACKUP_STAMP}.sql.gz"
```

将备份复制到项目目录之外，并用隔离数据库验证能够导入。若数据库由云厂商托管，应改用可验证恢复的快照/备份流程。

同时检查磁盘与现有日志：

```bash
df -h
docker compose logs --tail=100 mysql
docker compose logs --tail=100 backend
```

## 3. 一次性生成安全材料

### 3.1 固定卡密 pepper

仅在首次执行 `20260911_02` 前生成一次：

```bash
openssl rand -hex 32
```

把结果写入服务器 secret 管理或 `.env` 的 `CARD_LICENSE_PEPPER`。迁移后绝不能更换、遗失或重新生成该值；否则所有卡密 lookup 都会失效。它应与数据库备份一同纳入灾备，但不能写入 Git、工单或聊天记录。

### 3.2 生成 Ed25519 PKCS#8 私钥

```bash
install -d -m 700 secrets
openssl genpkey -algorithm Ed25519 -out secrets/keydesk-license-ed25519.pem
chmod 600 secrets/keydesk-license-ed25519.pem
openssl pkey -in secrets/keydesk-license-ed25519.pem -text -noout
```

最后一条命令必须显示 `ED25519 Private-Key`。不要输出或复制私钥正文。Compose 会把该文件只读挂载进后端，私钥不会进入数据库和客户端。

## 4. 更新 `.env`

用新版 `.env.example` 对照现有 `.env`，不要直接覆盖线上文件。至少确认：

```dotenv
CARD_ENV=production
CARD_PUBLIC_BASE_URL=https://card.ovorz.cn
CARD_CORS_ORIGINS=https://card.ovorz.cn
CARD_APP_VERSION=<本次版本>
CARD_GIT_SHA=<本次发布提交SHA>

CARD_SECRET_KEY=<原有或新的至少32位高熵值>
CARD_DEFAULT_ADMIN_PASSWORD=<非默认且至少12位>
CARD_ALLOW_DEV_RESET_LINK=false

CARD_LICENSE_SIGNING_KEY_FILE=/run/secrets/keydesk-license-ed25519.pem
CARD_LICENSE_SIGNING_KEY_FILE_HOST=./secrets/keydesk-license-ed25519.pem
CARD_LICENSE_SIGNING_KEY_ID=license-2026-01
CARD_LICENSE_PREVIOUS_PUBLIC_KEYS={}
CARD_LICENSE_PEPPER=<第3.1节生成且今后保持不变的值>
CARD_LICENSE_LEASE_TTL_SECONDS=300
CARD_LICENSE_NEXT_CHECK_SECONDS=60
CARD_LICENSE_REQUEST_WINDOW_SECONDS=120
CARD_LICENSE_NONCE_TTL_SECONDS=600
CARD_LICENSE_AUDIT_RETENTION_DAYS=90
```

保留现有 MySQL 与 SMTP 配置。`CARD_SECRET_KEY` 变更会使后台现有会话失效；`.env` 中修改 MySQL 密码不会自动修改已初始化数据库账号。

只检查配置语法，不要把会展开 secret 的完整配置粘贴到工单：

```bash
docker compose config --quiet
test -r secrets/keydesk-license-ed25519.pem
```

## 5. 获取发布提交并构建

推荐检出已确认的提交或标签：

```bash
git fetch --all --tags --prune
git checkout <本次发布Git-SHA或标签>
git status --short
git rev-parse HEAD
docker compose build --pull backend frontend
```

确认检出的 SHA 与 `.env` 中 `CARD_GIT_SHA` 完全相同。稳定观察结束前不要清理旧镜像。

## 6. 执行数据库迁移

先只启动数据库，再用新镜像显式迁移：

```bash
docker compose up -d mysql
docker compose ps mysql
docker compose run --rm --no-deps backend python -m app.preflight
docker compose run --rm --no-deps backend alembic upgrade head
docker compose run --rm --no-deps backend alembic current
```

预期：

```text
20260911_02 (head)
```

预检会在迁移前验证所有生产门禁、解析 Ed25519 私钥并校验轮换公钥 JSON。迁移会读取 `CARD_LICENSE_PEPPER`。若任一步出现私钥、pepper 不匹配、半迁移记录、重复 lookup 或约束错误，立即停止发布，不要启动新后端，不要直接修改生产数据；按第 10 节恢复发布前备份。

迁移后进行只读完整性检查：

```bash
docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -e "SELECT COUNT(*) AS non_reference_cards FROM auth_cards WHERE LEFT(auth_id,5) <> '\''CARD_'\''; SELECT COUNT(*) AS invalid_lookup FROM auth_cards WHERE license_lookup IS NULL OR CHAR_LENGTH(license_lookup) <> 64; SELECT COUNT(*) AS plaintext_event_values FROM event_logs WHERE auth_id LIKE '\''KM%'\'';"'
```

三个计数均应为 `0`。不要查询或输出历史完整卡密。

## 7. 切换服务

```bash
docker compose up -d --no-deps backend
docker compose ps backend
docker compose logs --tail=200 backend

docker compose up -d --no-deps frontend
docker compose ps
```

后端启动顺序固定为“生产配置/签名密钥预检 → `alembic upgrade head` → API”。不要为了让容器启动而换回开发默认 secret。

## 8. 发布后验收

### 8.1 健康、版本与 TLS

```bash
curl --fail --silent --show-error http://127.0.0.1:${CARD_HTTP_PORT:-8080}/health
curl --fail --silent --show-error https://card.ovorz.cn/health
curl --fail --show-error --head https://card.ovorz.cn/
```

健康响应的 `data` 必须包含：

- `status=ok`
- `schemaVersion=20260911_02`
- `protocolVersions=[1,2]`
- `activeSigningKid=license-2026-01`（或本次实际 kid）
- `sdkVersion=2.0.0`
- 正确的 `appVersion` 与 `gitSha`

公网 HTTPS 必须通过系统 CA 和主机名校验。仓库 Nginx 只提供容器内 HTTP，公网证书续期仍由外层代理/负载均衡负责。

### 8.2 无卡密的安全检查

```bash
curl --silent --show-error -H 'Content-Type: application/json' -d '{}' https://card.ovorz.cn/api/client/v2/license/validate
```

预期 HTTP 422，`error.code=INVALID_REQUEST`，并带 `error.requestId=req_...`。

后台确认：

- 实例页可设置最低协议、lease TTL、复验间隔并下载 v2 SDK。
- 卡密历史列表只显示 `KM••••<尾号>`，没有复制历史完整卡密按钮。
- CSV 只有 `cardRef` 与 `licenseLast4`，不包含可用卡密。
- 新建卡密只显示一次，关闭创建结果后不能再次取回。

### 8.3 专用测试卡 v2 验收

不要使用真实业务卡。创建专用实例/卡，保持该实例最低协议为 1，下载它的 v2 SDK：

1. 运行 `python smoke_test.py`，设备 A 首绑成功。
2. 设备 A 再次验证成功，lease 签名和 claims 校验通过。
3. 修改 SDK 测试夹具中的 lease 任一段，预期 `LEASE_SIGNATURE_INVALID` 或 `LEASE_CLAIMS_INVALID`。
4. 复制卡密和 installation ID，但改用新设备私钥，预期 409/`LICENSE_DEVICE_MISMATCH`。
5. 重放完全相同的已签名请求，预期 409/`REQUEST_REPLAYED`。
6. 后台撤销测试卡，再验证，预期 403/`LICENSE_REVOKED`。

完成后清理测试数据，只保存 request ID、卡记录引用、尾号和测试结论。

### 8.4 观察日志

```bash
docker compose logs --since=30m mysql
docker compose logs --since=30m backend
docker compose logs --since=30m frontend
```

重点检查迁移、签名私钥、数据库连接、429、5xx、CORS 和 TLS。日志不得包含完整卡密、lease、设备私钥、pepper、后台 token 或签名私钥。

## 9. Joom 客户端发布与 v1 切断

服务端上线后先保持 Joom 实例 `SWMNU4QGXW5R1Y` 的 `minimumProtocolVersion=1`。完成下列事项后才能切 2：

1. Joom 新包使用下载的官方 v2 SDK，生产 URL 与公钥不可由外部配置替换。
2. 所有采集、批量、产品、状态、停止、导出路由都有授权门禁。
3. 任务 ID、运行期 session token、Origin/CSRF 防护和长任务周期复验已完成。
4. 假服务器、复制设备、撤销中止和 EXE 级绕过回归均通过。
5. 后台遥测确认目标用户已使用 v2。

随后在实例管理将最低协议改为 2，并验证：

- v1 请求返回 HTTP 426/`PROTOCOL_UPGRADE_REQUIRED`；
- v2 请求继续签发有效短期 lease；
- 必要时迁移窗口内可把该实例改回 1，但不得回滚数据库或 pepper。

## 10. 回滚

### 尚未执行 `20260911_02`

可切回旧提交/镜像，重启服务并验证旧健康接口。数据库未迁移时不需要恢复数据。

### 已执行 `20260911_02`

禁止执行 Alembic downgrade，也不能只切旧代码。正确流程：

1. 停止前端、后端及所有写入方，保存故障日志。
2. 核对发布前 Git SHA、镜像 ID、目标数据库名和已验证备份。
3. 由数据库运维人员重建目标业务库并导入发布前备份。
4. 切回发布前代码/镜像，恢复当时 `.env`，启动旧服务。
5. 验证健康、管理员登录和只读数据后再恢复流量。

恢复数据库会覆盖迁移后的新增数据，属于破坏性操作，必须由有权限人员二次核对目标和备份。不要从文档复制未经核对的删库命令。

## 11. 完成标准

- Compose 服务健康，无持续重启。
- 公网 `/health`、TLS、Git SHA、schema、协议和 `kid` 正确。
- 三项迁移完整性计数均为 0。
- v2 正向、假签名、篡改、重放、复制设备、撤销测试有脱敏证据。
- 新卡单次展示和历史列表/CSV 脱敏已确认。
- 备份、pepper、签名私钥已进入安全灾备，且不在 Git 中。
- Joom 未完成客户端门禁前，实例仍保持最低协议 1，发布记录明确写明剩余项。

建议稳定观察至少 30 分钟后再清理旧镜像。只有 Joom 客户端门禁完成、实例切到 v2 且 P0 回归通过后，才能声明本次低成本假服务器绕过已完整关闭。
