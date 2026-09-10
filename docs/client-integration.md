# KeyDesk 客户端 v1 接入

新客户端只使用幂等接口 `POST /api/client/v1/license/validate`。`instanceKey` 只为旧协议迁移保留，不应嵌入新桌面客户端，也不能被视为客户端秘密。

## 最小配置

```json
{
  "baseUrl": "https://card.example.com",
  "softwareId": "SWxxxxxxxxxxxx",
  "version": "1.0.0"
}
```

将 `clients/python/keydesk-client.example.json` 复制为 `keydesk.json`，然后在业务入口调用：

```python
from clients.python import KeyDesk, LicenseError

license = KeyDesk.from_file("keydesk.json")
try:
    state = license.require_license(prompt=lambda: input("请输入卡密：").strip())
except LicenseError as exc:
    print(f"授权失败 [{exc.error_code}]: {exc}")
    raise SystemExit(1)
```

SDK 会在平台应用数据目录生成随机 `installationId`，首次成功后保存卡密和最小授权状态：

- Windows：`%LOCALAPPDATA%/KeyDesk/<softwareId>/`
- macOS：`~/Library/Application Support/KeyDesk/<softwareId>/`
- Linux：`$XDG_DATA_HOME/keydesk/<softwareId>/`，未设置时使用 `~/.local/share/keydesk/`

状态文件不应进入代码仓库或安装包。首版 v1 明确要求在线验证：服务端返回 `offlineGraceSeconds: 0`、`leaseToken: null` 和 `requiresOnline: true`，SDK 不会把本地状态误当作永久离线授权。

## HTTP 契约

```http
POST /api/client/v1/license/validate
Content-Type: application/json

{
  "softwareId": "SWxxxxxxxxxxxx",
  "licenseKey": "KMxxxxxxxxxxxxxxxxxxxx",
  "installationId": "INST-...",
  "clientVersion": "1.0.0"
}
```

首次使用的卡会在同一事务内原子绑定。已经激活的卡只有 installation ID 相同才成功；设备不同不会自动换绑，也不会消耗换绑次数。禁用、撤销、过期、黑白名单和字段校验均在修改状态之前完成。

成功示例：

```json
{
  "code": 200,
  "success": true,
  "data": {
    "status": "active",
    "expiresAt": "2026-10-10T12:00:00Z",
    "serverTime": "2026-09-10T12:00:00Z",
    "nextCheckAfterSeconds": 3600,
    "offlineGraceSeconds": 0,
    "leaseToken": null,
    "requiresOnline": true,
    "updateAvailable": true,
    "updateRequired": false,
    "latestVersion": "1.2.0",
    "minimumVersion": "1.0.0",
    "sha256": "..."
  }
}
```

失败使用正确 HTTP 状态和稳定错误码：

```json
{
  "success": false,
  "error": {
    "code": "LICENSE_DEVICE_MISMATCH",
    "message": "卡密已绑定其他设备",
    "retryable": false
  }
}
```

常用错误码：

| 错误码 | HTTP | 含义 |
| --- | ---: | --- |
| `INVALID_REQUEST` | 422 | 字段缺失、为空或存在未知字段 |
| `SOFTWARE_NOT_FOUND` | 404 | 软件 ID 不存在 |
| `LICENSE_NOT_FOUND` | 404 | 卡密不存在或不属于该软件 |
| `LICENSE_REVOKED` | 403 | 卡密已禁用或撤销 |
| `LICENSE_EXPIRED` | 403 | 卡密已到期 |
| `LICENSE_DEVICE_BLOCKED` | 403 | 命中黑名单或不在白名单 |
| `LICENSE_DEVICE_MISMATCH` | 409 | 已绑定其他安装 ID |
| `RATE_LIMITED` | 429 | 请求过频，可稍后重试 |

SDK 的异常提供 `error_code`、`http_status` 和 `retryable`。只有网络故障、服务端临时错误或明确标记为可重试的错误会有限重试；不会再因任意异常调用旧 `activate`。

## 旧协议迁移

旧 `/api/client/software/checkUpdate`、`/api/client/auth/activate`、`/api/client/auth/verify`、`/api/client/auth/unbind` 暂时保留，但现在强制要求正确、非空的 `instanceKey`：

- `verify` 只验证已激活且同设备的卡，不再隐式激活或换绑。
- `activate` 只负责首次绑定，拒绝空设备码、禁用卡和过期卡。
- 解绑必须使用匹配设备码；完成后卡回到 `unused`，下次绑定仍保留原到期时间。

新项目不要调用软件侧 `register/login/heartbeat/logout`；这组旧接口不属于卡密授权链路，也未由 v1 SDK 暴露。

## 部署前烟雾测试

部署完成后至少验证：

1. `/health` 的 `gitSha` 和 `schemaVersion` 与本次发布一致。
2. 旧接口缺失、空、错误 `instanceKey` 都失败，正确值成功。
3. v1 缺字段返回 422，错误卡密返回 404。
4. 测试卡首次绑定成功，同设备复验成功，不同设备返回 409。
5. 禁用和过期测试卡均返回 403。

不要关闭 TLS 校验，不要把完整卡密、实例密钥或 token 写入日志。
