# KeyDesk 客户端 v2 接入

新客户端统一使用 `POST /api/client/v2/license/validate` 和 Python SDK 2.0.0。v2 使用 Ed25519 服务端签名、每安装一把设备私钥、nonce 防重放和短期在线 lease；客户端不能再仅凭 `success=true` 或 `status=active` 判断授权成功。

## 获取官方接入包

在后台“实例管理 → 接入客户端”下载对应实例的 `keydesk-<softwareId>-python-v2.zip`。下载包包含：

- `keydesk.py`：已固化生产服务地址和受信任 Ed25519 公钥；
- `keydesk.json`：只包含软件 ID、当前客户端版本和展示用服务地址；
- `example.py`：业务入口示例；
- `smoke_test.py`：发布前真实签名链路烟雾测试。

生产包应使用后台下载的 SDK，不要直接复制仓库通用源码。通用源码没有生产信任根，只有显式配置 `trustedPublicKeys` 后才可用于开发测试。

安装依赖并接入：

```bash
pip install cryptography
python smoke_test.py
```

```python
from keydesk import KeyDesk, LicenseError

license = KeyDesk.from_file("keydesk.json")
try:
    state = license.require_license(prompt=lambda: input("请输入卡密：").strip())
except LicenseError as exc:
    print(f"授权失败 [{exc.error_code}] requestId={exc.request_id}: {exc}")
    raise SystemExit(1)
```

生产 SDK 始终使用内置 HTTPS 地址和内置公钥；同目录配置不能替换它们。不要修改 `BUILTIN_PRODUCTION_BASE_URL`、`BUILTIN_TRUSTED_LICENSE_KEYS` 或 TLS 校验行为。

## 设备身份与本地状态

SDK 首次运行会生成随机 `installationId`、Ed25519 设备密钥对，以及每次请求使用的 32 字节随机 nonce。

Windows 使用 DPAPI LocalMachine 保护设备私钥与卡密状态；其他系统使用权限为 `0600` 的文件作为兼容回退。设备私钥永不发送给服务端。本地文件损坏时 SDK 会停止运行，不会静默生成新私钥覆盖原身份。

默认数据目录：

- Windows：`%LOCALAPPDATA%/KeyDesk/<softwareId>/`
- macOS：`~/Library/Application Support/KeyDesk/<softwareId>/`
- Linux：`$XDG_DATA_HOME/keydesk/<softwareId>/`，未设置时为 `~/.local/share/keydesk/<softwareId>/`

不要将这些文件复制进安装包或代码仓库。复制卡密和 installation ID、但没有原设备私钥，不能克隆已经绑定的设备。需要换机时应由后台执行显式解绑，再由新设备重新绑定。

## v2 请求与设备证明

```http
POST /api/client/v2/license/validate
Content-Type: application/json

{
  "protocolVersion": 2,
  "softwareId": "SWxxxxxxxxxxxx",
  "licenseKey": "KMxxxxxxxxxxxxxxxxxxxx",
  "installationId": "INST-...",
  "clientVersion": "1.0.1",
  "devicePublicKey": "BASE64URL_RAW_ED25519_PUBLIC_KEY",
  "requestNonce": "BASE64URL_RANDOM_32_BYTES",
  "requestTime": "2026-09-11T01:00:00Z",
  "deviceSignature": "BASE64URL_ED25519_SIGNATURE"
}
```

签名内容是固定顺序的规范字节串：

```text
KEYDESK-LICENSE-V2
<softwareId>
<SHA256(规范化卡密)的小写十六进制>
<installationId>
<clientVersion>
<devicePublicKey>
<requestNonce>
<requestTime>
```

服务端拒绝未知字段、非规范 Base64URL、时间超窗、重复 nonce、错误设备签名和设备公钥变更。首次绑定在事务内原子完成；并发首绑也只有一个设备能够成功。

## 签名 lease

成功响应包含有效期很短的 `leaseToken`。SDK 先验证 Ed25519 签名和受信任 `kid`，再核对：

- `iss` 与内置服务地址；
- `aud` 与 software ID；
- `installationId` 与当前安装；
- `deviceKeyThumbprint` 与本机设备私钥；
- `clientVersion`、`status`、`protocolVersion`；
- `iat`、`nbf`、`exp`；
- 外层更新字段与签名 claims 一致。

无签名、错误签名、篡改 claim、过期 lease 或字段不一致都会失败。lease 不写入本地状态，Joom 首版必须在线，`offlineGraceSeconds=0`。

## 稳定错误码

| 错误码 | HTTP | 含义 |
| --- | ---: | --- |
| `INVALID_REQUEST` | 422 | 字段缺失、格式错误或出现未知字段 |
| `SOFTWARE_NOT_FOUND` | 404 | 软件不存在 |
| `LICENSE_NOT_FOUND` | 404 | 卡密不存在或不属于该软件 |
| `LICENSE_REVOKED` | 403 | 卡密已禁用或撤销 |
| `LICENSE_EXPIRED` | 403 | 卡密已过期 |
| `LICENSE_DEVICE_BLOCKED` | 403 | 命中黑名单或不在白名单 |
| `LICENSE_DEVICE_MISMATCH` | 409 | 安装 ID 或设备公钥不匹配 |
| `DEVICE_PROOF_INVALID` | 401 | 设备证明无效 |
| `REQUEST_EXPIRED` | 401 | 请求时间超窗 |
| `REQUEST_REPLAYED` | 409 | nonce 已使用 |
| `CLIENT_UPDATE_REQUIRED` | 426 | 客户端版本低于实例最低版本 |
| `PROTOCOL_UPGRADE_REQUIRED` | 426 | v1 已被实例策略关闭 |
| `RATE_LIMITED` | 429 | 请求过频，可稍后重试 |
| `SERVICE_UNAVAILABLE` | 503 | 签名服务暂不可用 |
| `LEASE_SIGNATURE_INVALID` | 客户端 | lease 缺失、签名错误或信任根不匹配 |
| `LEASE_CLAIMS_INVALID` | 客户端 | lease claims 与当前请求不一致 |

所有 v2 服务端错误都带 `requestId`。日志只记录卡记录引用、HMAC 前缀、卡密尾号和设备摘要，不得记录完整卡密、设备私钥或 lease。

## 协议迁移

v1 仅用于迁移旧客户端。发布顺序必须是：

1. 先部署同时支持 v1/v2 的服务端，实例最低协议保持 `1`。
2. 发布使用官方 v2 SDK 的新 Joom 客户端。
3. 观察实例的 `lastProtocolVersion`、`lastClientVersion` 和 `lastProtocolAt`。
4. 用户迁移完成后，在实例后台将 `minimumProtocolVersion` 调为 `2`。
5. 验证 v1 返回 HTTP 426/`PROTOCOL_UPGRADE_REQUIRED`，v2 仍正常。

已由 v1 绑定且 installation ID 相同的卡，第一次有效 v2 请求可一次性认领设备公钥；之后更换公钥会被拒绝。不要在新客户端发布前提前关闭 v1。

## Joom 业务门禁

SDK 只能建立官方服务信任链；Joom 仓库仍必须同步完成：

- 固定生产域名和 SDK 公钥；
- `/api/scrape`、批量采集、产品、状态、停止和导出全部检查授权；
- 任务 ID 改为 UUIDv4 或高熵随机值；
- 本机 API 增加每次启动随机 session token 和 Origin/CSRF 防护；
- 长任务每页或每批次复验，撤销后立即中止；
- 启动新任务前拒绝 `updateRequired=true`。

在这些 Joom 客户端改动与 EXE 级绕过回归完成前，只能说“卡密服务 v2 已就绪”，不能宣称完整绕过已经关闭。纯本地 Python/PyInstaller 程序也不存在绝对不可破解保证；强保护需要把不可替代的核心能力迁移到服务端。

## 验收清单

至少保存以下测试证据：

1. 正常首绑和同设备复验成功。
2. 无签名假响应、错误私钥、修改 token 任一字符均失败。
3. 复制卡密与 installation ID、但使用另一设备私钥时失败。
4. nonce 重放与过期请求失败。
5. 撤销和过期卡失败，且不修改绑定数据。
6. v1 切断可按单实例启用，并可在迁移窗口内改回 `1`。
