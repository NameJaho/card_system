# 客户端接入文档

本文档面向需要把自己的软件接入 KeyDesk 卡密系统的开发者。推荐方式是：后台创建实例后复制客户端配置，在业务程序中引入 SDK，然后只维护一个 `keydesk-client.json` 配置文件。

## 推荐接入方式

### 1. 后台创建实例

1. 登录后台，进入 `实例管理`。
2. 创建软件实例，填写名称、版本、最低版本、下载地址、公告等信息。
3. 在实例列表中复制 `软件 ID` 和 `实例密钥`，或直接点击 `复制配置`。
4. 进入 `网络验证`，为该实例创建卡密，交付给最终用户。

`软件 ID` 用于定位实例，`实例密钥` 用于客户端请求校验。业务客户端不要使用后台账号、后台密码或后台 token。

### 2. 引入 Python SDK

项目内置标准库 SDK，无需额外安装第三方依赖：

```text
clients/python/keydesk_client.py
clients/python/keydesk-client.example.json
clients/python/example_app.py
```

接入自己的 Python 项目时有两种方式：

- 直接复制 `clients/python/keydesk_client.py` 到业务项目，然后 `from keydesk_client import KeyDeskApp`。
- 如果业务项目和本仓库在同一工程内，可以 `from clients.python import KeyDeskApp`。

推荐业务代码只依赖 `KeyDeskApp`，不要在业务层手动拼接口参数。

### 3. 创建配置文件

复制模板：

```bash
cp clients/python/keydesk-client.example.json keydesk-client.json
```

配置示例：

```json
{
  "projectName": "Demo Desktop App",
  "baseUrl": "http://127.0.0.1:8080",
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "version": "1.0.0",
  "authId": "",
  "macid": "",
  "licenseFile": ".keydesk-license.json",
  "deviceFile": ".keydesk-device",
  "timeout": 10,
  "heartbeatInterval": 60,
  "autoActivate": true
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `projectName` | 是 | 项目名称，用于生成默认设备码和本地状态标识。 |
| `baseUrl` | 是 | 服务地址，本地通常是 `http://127.0.0.1:8000`，Docker 默认是 `http://服务器IP:8080`。 |
| `softwareId` | 是 | 后台实例的软件 ID。 |
| `instanceKey` | 是 | 后台实例密钥，SDK 会随客户端接口提交。 |
| `version` | 否 | 当前客户端版本，用于检查更新。 |
| `authId` | 否 | 预置卡密。通常留空，由用户首次输入后保存到授权文件。 |
| `macid` | 否 | 固定设备码。留空时 SDK 会自动生成并写入 `deviceFile`。 |
| `licenseFile` | 否 | 授权状态文件路径，默认 `.keydesk-license.json`。 |
| `deviceFile` | 否 | 设备码状态文件路径，默认 `.keydesk-device`。 |
| `timeout` | 否 | HTTP 请求超时时间，单位秒。 |
| `heartbeatInterval` | 否 | 用户心跳循环间隔，单位秒。 |
| `autoActivate` | 否 | `require_license()` 验证失败时是否自动尝试激活，默认 `true`。 |

建议把本地状态文件加入业务项目的 `.gitignore`：

```gitignore
keydesk-client.json
.keydesk-device
.keydesk-license.json
```

如果你希望配置文件进入代码仓库，可以提交一个 `keydesk-client.example.json`，把真实 `instanceKey` 和测试卡密留空。

### 4. 业务程序调用

最小示例：

```python
from clients.python import KeyDeskApp, KeyDeskError

app = KeyDeskApp.from_file("keydesk-client.json")

try:
    update = app.check_update()
    if update.get("force"):
        print(f"需要升级到 {update.get('version')}: {update.get('url')}")
        raise SystemExit(1)

    card = app.require_license()
    variables = app.cloud_variables()
    print("授权通过")
    print("到期时间:", card.get("endTime") or "永久")
    print("云变量:", variables)
except KeyDeskError as exc:
    print(f"授权失败: {exc}")
    raise SystemExit(1)
```

首次激活时，如果配置文件没有 `authId`，可以让用户输入卡密：

```python
from clients.python import KeyDeskApp

app = KeyDeskApp.from_file("keydesk-client.json")
auth_id = input("请输入卡密: ").strip()
card = app.activate(auth_id)
print("激活成功:", card.get("endTime") or "永久")
```

之后 SDK 会把卡密保存到 `licenseFile`，下次启动直接调用：

```python
card = app.require_license()
```

### 5. 软件侧用户系统

如果你的软件还需要自己的用户登录，可以使用 SDK 的用户方法：

```python
from clients.python import KeyDeskApp

app = KeyDeskApp.from_file("keydesk-client.json")

customer = app.login_user("user@example.com", "client123456")
print("用户 ID:", customer["customerId"])

app.heartbeat()
app.logout_user()
```

长期运行的程序可以启动心跳循环：

```python
app.heartbeat_loop()
```

心跳间隔默认读取 `heartbeatInterval`，建议设置在 30 到 120 秒之间。

## SDK 方法速查

| 方法 | 用途 | 返回 |
| --- | --- | --- |
| `KeyDeskApp.from_file(path)` | 从 JSON/TOML 配置创建应用客户端。 | `KeyDeskApp` |
| `check_update(version=None)` | 检查更新、公告、下载地址和强制升级状态。 | 更新数据字典 |
| `activate(auth_id=None)` | 激活卡密并保存授权状态。 | 卡密数据字典 |
| `verify(auth_id=None)` | 验证卡密并刷新授权状态。 | 卡密数据字典 |
| `require_license(auth_id=None)` | 推荐业务入口：先验证，必要时自动激活。 | 卡密数据字典 |
| `unbind(auth_id=None)` | 使用当前设备码解绑卡密。 | 卡密数据字典 |
| `cloud_variables(as_dict=True)` | 读取启用的全局变量和实例变量。 | 字典或原始列表 |
| `register_user(email, password, nick_name="")` | 注册软件侧用户。 | 用户数据字典 |
| `login_user(email, password)` | 登录软件侧用户并保存 `customerId`。 | 用户数据字典 |
| `heartbeat(customer_id="")` | 上报用户在线心跳。 | 心跳数据字典 |
| `logout_user(customer_id="")` | 上报用户退出。 | 退出数据字典 |
| `heartbeat_loop(customer_id="", interval=None)` | 按间隔循环心跳。 | 不返回 |

底层 `KeyDeskClient` 仍然可用，适合二次封装或非配置模式，但业务接入优先使用 `KeyDeskApp`。

## CLI 调试

SDK 同时提供命令行工具，便于开发期测试配置和接口。

配置模式：

```bash
python3 clients/python/keydesk_client.py --config keydesk-client.json check-update
python3 clients/python/keydesk_client.py --config keydesk-client.json bind-license --auth-id KMxxxxxxxxxxxxxxxxxxxx
python3 clients/python/keydesk_client.py --config keydesk-client.json verify
python3 clients/python/keydesk_client.py --config keydesk-client.json vars
python3 clients/python/keydesk_client.py --config keydesk-client.json demo
```

兼容旧参数模式：

```bash
python3 clients/python/keydesk_client.py \
  --base-url http://127.0.0.1:8080 \
  --software-id SWxxxxxxxxxxxx \
  --instance-key IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
  --auth-id KMxxxxxxxxxxxxxxxxxxxx \
  --macid DEMO-MACHINE-1 \
  verify
```

## 本地状态文件

SDK 会维护两个本地状态文件：

| 文件 | 默认路径 | 作用 |
| --- | --- | --- |
| 授权文件 | `.keydesk-license.json` | 保存已激活卡密、到期时间、用户 ID 等运行状态。 |
| 设备文件 | `.keydesk-device` | 保存自动生成的稳定设备码。 |

`macid` 留空时，SDK 会根据项目名、系统信息和用户环境生成一个哈希设备码，并写入 `deviceFile`。如果你需要更强的设备绑定策略，可以在配置里显式传入自己的 `macid`，或在业务程序中用更可靠的机器指纹生成后写入配置。

不要直接上传用户隐私明文，例如身份证、手机号、完整硬盘序列号。建议使用应用安装 ID 或机器特征哈希。

## 客户端 API

SDK 已封装以下接口。其他语言接入时，可以按本节直接调用 HTTP API。所有客户端接口统一使用 `POST` 和 JSON 请求体，服务前缀为 `/api/client`。

统一响应：

```json
{
  "code": 200,
  "success": true,
  "message": "请求成功",
  "data": {}
}
```

判断规则：

- `success === true`：读取 `data`。
- `success === false`：读取 `message` 并提示用户或记录日志。
- HTTP 非 200、超时、JSON 解析失败：按网络异常处理。

所有接口都建议携带 `instanceKey`：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

当前服务端为了兼容旧客户端，允许不传 `instanceKey`；只要客户端传了该字段，就会进行实例密钥校验，错误时返回 `实例密钥错误`。新接入程序必须配置并提交实例密钥。

### 检查更新

```http
POST /api/client/software/checkUpdate
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "version": "1.0.0",
  "macid": "DEMO-MACHINE-1"
}
```

返回重点字段：

| 字段 | 说明 |
| --- | --- |
| `version` | 后台配置的最新版本。 |
| `lowVersion` | 最低可用版本。 |
| `force` | 是否强制更新。 |
| `url` | 下载地址。 |
| `notice` | 公告。 |
| `md5` | 安装包校验值。 |

### 激活卡密

```http
POST /api/client/auth/activate
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "authId": "KMxxxxxxxxxxxxxxxxxxxx",
  "macid": "DEMO-MACHINE-1"
}
```

首次激活会绑定当前设备码。如果卡密已绑定其他设备、命中黑名单、不在白名单或已过期，会返回业务失败。

### 验证卡密

```http
POST /api/client/auth/verify
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "authId": "KMxxxxxxxxxxxxxxxxxxxx",
  "macid": "DEMO-MACHINE-1"
}
```

返回重点字段：

| 字段 | 说明 |
| --- | --- |
| `state` | `unused`、`active`、`expired`、`disabled`。 |
| `macid` | 当前绑定设备码。 |
| `bindCount` | 允许换绑次数，`null` 表示不限。 |
| `bindUsed` | 已使用换绑次数。 |
| `endTime` | 到期时间，空字符串表示永久。 |

### 解绑卡密

```http
POST /api/client/auth/unbind
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "authId": "KMxxxxxxxxxxxxxxxxxxxx",
  "macid": "DEMO-MACHINE-1"
}
```

客户端解绑需要当前设备码匹配。后台管理员也可以在 `网络验证` 页面手动解绑或换绑。

### 读取云变量

```http
POST /api/client/cloudVariables/list
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

返回示例：

```json
{
  "success": true,
  "data": [
    {
      "key": "api_host",
      "value": "https://api.example.com",
      "status": "y",
      "softwareId": ""
    }
  ]
}
```

系统会同时返回全局变量和当前实例变量，且只返回启用状态的变量。

### 软件侧用户注册

```http
POST /api/client/user/register
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "email": "user@example.com",
  "password": "client123456",
  "nickName": "客户端用户"
}
```

### 软件侧用户登录

```http
POST /api/client/user/login
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "email": "user@example.com",
  "password": "client123456"
}
```

登录成功后保存返回的 `customerId`，用于心跳和退出。SDK 会自动保存到 `licenseFile`。

### 用户心跳

```http
POST /api/client/user/heartbeat
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "customerId": "CUxxxxxxxxxxxxxx",
  "macid": "DEMO-MACHINE-1"
}
```

### 用户退出

```http
POST /api/client/user/logout
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "instanceKey": "IKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "customerId": "CUxxxxxxxxxxxxxx"
}
```

## 常见错误

| 错误 | 排查方向 |
| --- | --- |
| `实例不存在` | `softwareId` 不正确，或客户端请求到了错误服务器。 |
| `实例密钥错误` | `instanceKey` 不属于该实例，重新从后台复制配置。 |
| `卡密不存在` | `authId` 不属于该实例，或用户输入错误。 |
| `卡密已绑定其他设备` | 当前卡密已绑定其他设备码，需要后台解绑或换绑。 |
| `换绑次数不足` | 后台创建卡密时限制了换绑次数。 |
| `卡密已过期` | 有效期已到，需要续期或重新发卡。 |
| `命中黑名单` | 设备码在后台黑名单中。 |
| `不在白名单` | 后台设置了白名单，但当前设备码未加入。 |
| `Network error` | 服务地址、端口、HTTPS 证书或网络连通性异常。 |

## 安全建议

- 客户端只调用 `/api/client/*`，不要在客户端保存后台管理员账号、密码或 token。
- 生产环境建议启用 HTTPS，避免卡密、实例密钥和设备码被明文传输。
- `instanceKey` 是实例级校验密钥，不等于后台管理权限；泄露后应删除并重建实例，或扩展服务端支持重置实例密钥。
- 对验证结果可以做短时间本地缓存改善体验，但关键功能仍应定期向服务器验证。
- 发布安装包前检查 `keydesk-client.json`，不要把测试卡密或个人设备码打进公共模板。
