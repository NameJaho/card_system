# 客户端接入文档

本文档面向需要把软件接入 KeyDesk 卡密系统的开发者。你需要先在后台完成实例和卡密配置，然后在客户端程序里调用 `/api/client/*` 接口完成更新检查、卡密验证、云变量读取和用户心跳。

## 接入前准备

1. 登录后台，进入 `实例列表`，创建一个软件实例。
2. 复制实例的 `软件 ID`，下文统一写作 `softwareId`。
3. 进入 `网络验证`，点击 `新增卡密`，选择实例、数量、有效期和换绑次数。
4. 复制生成的卡密，下文统一写作 `authId`。
5. 客户端生成稳定设备码，下文统一写作 `macid`。

设备码建议由机器特征生成，例如硬盘序列号、主板序列号、系统用户 ID、应用安装 ID 的组合哈希。不要直接上传隐私明文。

## 服务地址

本地开发时：

```text
http://127.0.0.1:8000
```

Docker 部署后，如果使用默认端口：

```text
http://服务器IP:8080
```

如果通过 Nginx 前端访问，客户端接口仍然使用同一个域名，路径为 `/api/client/...`。

## 统一响应格式

所有客户端接口都返回 JSON：

```json
{
  "code": 200,
  "success": true,
  "message": "请求成功",
  "data": {}
}
```

客户端判断规则：

- `success === true`：请求成功，读取 `data`。
- `success === false`：请求失败，向用户展示或记录 `message`。
- 网络超时、HTTP 非 200、JSON 解析失败：按网络异常处理，可提示用户稍后重试。

## 推荐接入流程

1. 程序启动后调用 `检查更新`，判断是否需要提示升级。
2. 如果本地未保存卡密，要求用户输入卡密并调用 `激活卡密`。
3. 每次启动或关键功能使用前调用 `验证卡密`。
4. 验证成功后读取 `云变量`，用于开关、公告、远程配置等。
5. 如果使用软件侧用户系统，登录后定时调用 `用户心跳`，退出时调用 `用户退出`。

## Python 示例客户端

项目已提供可直接运行的标准库客户端：

```bash
python3 clients/python/keydesk_client.py \
  --base-url http://127.0.0.1:8000 \
  --software-id SWxxxxxxxxxxxx \
  --auth-id KMxxxxxxxxxxxxxxxxxxxx \
  --macid DEMO-MACHINE-1 \
  verify
```

检查更新：

```bash
python3 clients/python/keydesk_client.py \
  --base-url http://127.0.0.1:8000 \
  --software-id SWxxxxxxxxxxxx \
  --version 1.0.0 \
  --macid DEMO-MACHINE-1 \
  check-update
```

激活卡密：

```bash
python3 clients/python/keydesk_client.py \
  --base-url http://127.0.0.1:8000 \
  --software-id SWxxxxxxxxxxxx \
  --auth-id KMxxxxxxxxxxxxxxxxxxxx \
  --macid DEMO-MACHINE-1 \
  activate
```

读取云变量：

```bash
python3 clients/python/keydesk_client.py \
  --base-url http://127.0.0.1:8000 \
  --software-id SWxxxxxxxxxxxx \
  vars
```

软件侧用户登录并心跳：

```bash
python3 clients/python/keydesk_client.py \
  --base-url http://127.0.0.1:8000 \
  --software-id SWxxxxxxxxxxxx \
  --email user@example.com \
  --password client123456 \
  login
```

导入到自己的 Python 程序：

```python
from clients.python.keydesk_client import KeyDeskClient, KeyDeskError

client = KeyDeskClient("http://127.0.0.1:8000")

try:
    result = client.verify(
        software_id="SWxxxxxxxxxxxx",
        auth_id="KMxxxxxxxxxxxxxxxxxxxx",
        macid="DEMO-MACHINE-1",
    )
    card = result["data"]
    print("验证成功，到期时间：", card["endTime"] or "永久")
except KeyDeskError as exc:
    print("验证失败：", exc)
```

## 接口详情

### 检查更新

```http
POST /api/client/software/checkUpdate
Content-Type: application/json
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "version": "1.0.0",
  "macid": "DEMO-MACHINE-1"
}
```

返回字段重点：

- `version`：后台配置的最新版本。
- `lowVersion`：最低可用版本。
- `force`：是否强制更新。
- `url`：下载地址。
- `notice`：公告。
- `md5`：安装包校验值。

### 激活卡密

```http
POST /api/client/auth/activate
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "authId": "KMxxxxxxxxxxxxxxxxxxxx",
  "macid": "DEMO-MACHINE-1"
}
```

说明：

- 首次激活会绑定当前设备码。
- 如果卡密已绑定其他设备，会返回失败。
- 如果命中黑名单或不在白名单，会返回失败。

### 验证卡密

```http
POST /api/client/auth/verify
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "authId": "KMxxxxxxxxxxxxxxxxxxxx",
  "macid": "DEMO-MACHINE-1"
}
```

返回字段重点：

- `state`：`unused`、`active`、`expired`、`disabled`。
- `macid`：当前绑定设备码。
- `bindCount`：允许换绑次数，`null` 表示不限。
- `bindUsed`：已使用换绑次数。
- `endTime`：到期时间，空字符串表示永久。

### 解绑卡密

```http
POST /api/client/auth/unbind
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "authId": "KMxxxxxxxxxxxxxxxxxxxx",
  "macid": "DEMO-MACHINE-1"
}
```

说明：客户端解绑需要当前设备码匹配。后台管理员也可以在 `网络验证` 页面手动解绑或换绑。

### 读取云变量

```http
POST /api/client/cloudVariables/list
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx"
}
```

返回示例：

```json
{
  "success": true,
  "data": [
    { "key": "api_host", "value": "https://api.example.com", "status": "y", "softwareId": "" }
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
  "email": "user@example.com",
  "password": "client123456"
}
```

登录成功后保存返回的 `customerId`，用于心跳和退出。

### 用户心跳

```http
POST /api/client/user/heartbeat
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "customerId": "CUxxxxxxxxxxxxxx",
  "macid": "DEMO-MACHINE-1"
}
```

建议间隔：30 到 120 秒。不要设置过短，避免无意义的服务器压力。

### 用户退出

```http
POST /api/client/user/logout
```

请求：

```json
{
  "softwareId": "SWxxxxxxxxxxxx",
  "customerId": "CUxxxxxxxxxxxxxx"
}
```

## 常见错误

- `实例不存在`：`softwareId` 不正确，或客户端请求到了错误服务器。
- `卡密不存在`：`authId` 不属于该实例，或用户输入错误。
- `卡密已绑定其他设备`：当前卡密已绑定其他设备码，需要后台解绑/换绑。
- `换绑次数不足`：后台创建卡密时限制了换绑次数。
- `卡密已过期`：有效期已到，需要续期或重新发卡。
- `命中黑名单`：设备码在后台黑名单中。
- `不在白名单`：后台设置了白名单，但当前设备码未加入。

## 安全建议

- 客户端不要硬编码后台管理员账号、密码或后台 token。
- 只调用 `/api/client/*` 接口，后台 `/api/adm/*` 接口只给管理后台使用。
- 生产环境建议启用 HTTPS。
- 设备码不要直接使用用户隐私明文，建议做哈希或生成应用内安装 ID。
- 对验证结果做本地短缓存可以改善体验，但关键功能仍应定期向服务器验证。
