# 安全修复迁移与发布说明

当前数据库 head 为 `20260911_02`。本次迁移在 `20260910_01` 的登录、租户隔离和 v1 加固基础上增加签名授权协议 v2。

## `20260911_02` 的数据变化

- `auth_cards.auth_id` 从可使用的完整卡密改为不透明 `CARD_...` 记录引用。
- 新增 `license_lookup=HMAC-SHA256(CARD_LICENSE_PEPPER, normalized_license)` 和仅展示用 `license_last4`。
- 新增安装设备公钥、指纹、协议版本和撤销时间字段。
- 新增软件实例的最低协议、lease TTL、复验间隔、策略版本和协议遥测字段。
- 新增 `license_request_nonces`、`license_audit_events`、`license_signing_keys`。
- 历史 `event_logs.auth_id` 中能对应到现存卡的明文会替换为卡记录引用；孤立的 `KM...` 值会改为 HMAC 前缀与尾号。

迁移后数据库不能再次展示旧完整卡密。新卡只在创建响应中显示一次，历史列表和 CSV 只返回记录引用与尾号。

## 不可变 pepper

迁移前必须生成并永久保存独立的高熵 `CARD_LICENSE_PEPPER`：

```bash
openssl rand -hex 32
```

这个值不是登录 JWT secret，也不是签名私钥。它必须放入 secret 管理或仅 root 可读的 `.env`，并纳入灾备。迁移后更换或丢失 pepper 会导致所有卡密查询失效；不能通过轮换恢复。生产迁移会拒绝空值、开发默认值和少于 32 位的值。

若迁移发现已有 `license_lookup` 与当前 pepper 不匹配，或发现 `auth_id` 已变成 `CARD_...` 但 lookup 尚未写入，会失败关闭。此时不要编造新 pepper 或手改记录，应恢复迁移前备份并查明原因。

## Ed25519 签名密钥

生成 PKCS#8 PEM 私钥并限制权限：

```bash
install -d -m 700 secrets
openssl genpkey -algorithm Ed25519 -out secrets/keydesk-license-ed25519.pem
chmod 600 secrets/keydesk-license-ed25519.pem
openssl pkey -in secrets/keydesk-license-ed25519.pem -pubout -out secrets/keydesk-license-ed25519.pub.pem
```

私钥文件、pepper 和 `.env` 不得提交到 Git、写入镜像或放入客户端。Compose 默认把宿主机 `./secrets/keydesk-license-ed25519.pem` 只读挂载到 `/run/secrets/keydesk-license-ed25519.pem`。

密钥轮换时，先把旧公钥以 `kid -> Base64URL(raw Ed25519 public key)` JSON 放入 `CARD_LICENSE_PREVIOUS_PUBLIC_KEYS`，发布包含新旧公钥的客户端，再切换当前私钥和 `CARD_LICENSE_SIGNING_KEY_ID`。不要把可被替换的远程 JWKS 当作唯一信任根。

## 发布顺序

1. 停止写入，备份数据库，并实际验证备份可读取/可恢复。
2. 固定且备份 `CARD_LICENSE_PEPPER`，生成签名私钥。
3. 配置 `CARD_ENV=production`、HTTPS 公网地址、签名密钥路径/`kid` 和所有现有 secret。
4. 构建新镜像，单独运行 `alembic upgrade head`。
5. 确认 `alembic current` 为 `20260911_02 (head)` 后启动后端和前端。
6. 检查 `/health` 的 schema、Git SHA、协议列表和 active signing kid。
7. 使用专用卡运行 v2 正向与篡改负向测试。
8. 保持实例 `minimumProtocolVersion=1`，先发布 Joom v2 客户端。
9. 观察迁移率后，再按实例切换为 `2`。

```bash
docker compose run --rm --no-deps backend python -m app.preflight
docker compose run --rm --no-deps backend alembic upgrade head
docker compose run --rm --no-deps backend alembic current
```

后端容器的固定启动顺序也是“生产配置/签名密钥预检 → 迁移 → API”，避免不可逆迁移完成后才发现私钥不可用。

## 生产启动门禁

`CARD_ENV=production` 时，下列任一情况会拒绝启动：

- `CARD_SECRET_KEY` 或默认管理员密码仍为示例值/长度不足；
- `CARD_PUBLIC_BASE_URL` 不是 HTTPS；
- 开启开发密码重置链接；
- 数据库 URL 仍使用示例密码；
- Ed25519 私钥缺失、不可读或算法不正确；
- 签名 `kid` 仍为开发默认值；
- pepper 未配置或不安全；
- lease TTL、复验间隔超出允许范围。

## 回滚

`20260911_02` 会删除数据库中旧完整卡密，故意不提供安全 downgrade。迁移一旦完成，不能仅切回旧代码，也不能执行 `alembic downgrade` 恢复卡密。正确回滚方式是：停止写入，恢复发布前 Git SHA/镜像，并恢复发布前数据库备份。

恢复会覆盖迁移后的新增数据，必须由运维人员核对目标库和备份后执行。完整步骤见 [production-update.md](production-update.md)。

## 仍不属于服务端迁移的事项

本迁移不会自动修改 Joom 仓库或已发布 EXE。Joom 仍需固定生产 URL/公钥、保护全部本地业务路由、使用随机任务 ID 和运行期 session token，并在长任务中周期复验。完成这些客户端工作并将对应实例最低协议切到 2 之前，不应宣称完整绕过已修复。
