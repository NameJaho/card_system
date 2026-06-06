# 卡密系统复刻版

这是一个从零实现的卡密/网络验证管理系统，功能参考用户提供的后台系统，但不复制原站品牌素材、Logo 或专有文案。系统包含管理后台、软件侧验证 API、权限/子账户、事件日志、云变量、黑白名单和 Docker 部署配置。

## 功能清单

- 后台账号：登录、超级管理员创建账号、找回密码、免密码登录标记清除、个人资料修改、OpenId/AccountToken 重新生成。
- 数据面板：活跃实例、日访问、日激活、月访问、访问曲线、实例访问排行。
- 实例管理：创建、搜索、编辑、删除实例，维护版本、最低版本、强制更新、下载地址、MD5、公告、备注。
- 网络验证：创建卡密、搜索卡密、导出 CSV、批量删除、单个删除、修改备注、解绑/换绑、绑定次数，并标识卡密创建者姓名和角色。
- 用户管理：软件侧注册用户查询、关联实例信息、删除用户。
- 云变量：全局变量和实例变量，支持启用/停用，保存前校验重复。
- 黑白名单：按实例维护白名单/黑名单，软件侧验证时生效。
- 事件日志：记录后台登录、软件侧检查更新、激活、验证、解绑、用户注册登录、心跳等事件。
- 子账户：创建/编辑/删除子账户，分配实例范围和细粒度权限。
- 软件侧 API：检查更新、激活卡密、验证卡密、解绑、读取云变量、用户注册/登录/心跳/退出。

## 技术栈

- 前端：Vue 3、Vite、Element Plus、ECharts。
- 后端：FastAPI、SQLAlchemy，默认本地开发可用 SQLite。
- 数据库：Docker 部署默认使用 MySQL 8.4，字符集为 `utf8mb4`。
- 部署：Docker Compose、Nginx 反向代理。

生产部署已经内置 MySQL 服务，后端通过 `CARD_DATABASE_URL=mysql+pymysql://...` 连接数据库。MySQL 数据默认持久化到项目目录下的 `runtime/mysql`，重启和重新构建镜像不会丢数据。

## 本地开发

后端：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`。默认账号：

```text
账号：admin
密码：admin123456
```

## Docker + MySQL 部署到 Linux

在 Linux 服务器安装 Docker 和 Docker Compose 插件后：

```bash
cp .env.example .env
# 编辑 .env，至少修改 CARD_SECRET_KEY、MYSQL_ROOT_PASSWORD、MYSQL_PASSWORD 和默认管理员密码
docker compose up -d --build
```

访问：

```text
http://服务器IP:8080
```

如需改端口，修改 `.env`：

```text
CARD_HTTP_PORT=80
```

查看日志：

```bash
docker compose logs -f mysql
docker compose logs -f backend
docker compose logs -f frontend
```

查看服务状态：

```bash
docker compose ps
curl http://127.0.0.1:${CARD_HTTP_PORT:-8080}/health
```

停止：

```bash
docker compose down
```

保留数据重启：

```bash
docker compose restart
```

清空数据：

```bash
docker compose down
rm -rf runtime/mysql
```

OpenClaw 安装流程见 [docs/openclaw-deploy.md](docs/openclaw-deploy.md)。

## 环境变量

- `CARD_HTTP_PORT`：前端 Nginx 暴露端口。
- `CARD_SECRET_KEY`：JWT 签名密钥，生产必须修改。
- `CARD_ALLOW_DEV_RESET_LINK`：是否允许找回密码接口直接返回重置 token，生产默认关闭。
- `CARD_DEFAULT_ADMIN_USER`：初始化管理员账号。
- `CARD_DEFAULT_ADMIN_PASSWORD`：初始化管理员密码。
- `CARD_DEFAULT_ADMIN_EMAIL`：初始化管理员邮箱。
- `PYTHON_IMAGE` / `NODE_IMAGE` / `NGINX_IMAGE`：构建后端、前端和前端运行镜像的基础镜像；如果服务器访问 Docker Hub 不稳定，可改成可访问镜像源中的等价镜像。
- `MYSQL_ROOT_PASSWORD`：MySQL root 密码。
- `MYSQL_IMAGE`：MySQL 镜像，默认 `mysql:8.4`；如果服务器拉取 Docker Hub 失败，可改为内网镜像源的等价 MySQL 镜像。
- `MYSQL_DATABASE`：业务数据库名。
- `MYSQL_USER`：业务数据库用户名。
- `MYSQL_PASSWORD`：业务数据库密码。
- `MYSQL_DATA_DIR`：MySQL 宿主机持久化目录，默认 `./runtime/mysql`。

首次启动时如果 MySQL 为空，会自动建表并创建默认超级管理员和演示实例/卡密。

## 后台接口

后台接口统一前缀为 `/api/adm`，请求头使用：

```text
token: <登录返回的 token>
```

统一响应格式：

```json
{
  "code": 200,
  "success": true,
  "message": "请求成功",
  "data": {}
}
```

主要接口：

- `/api/adm/login`
- `/api/adm/register`（已关闭，仅返回提示）
- `/api/adm/user`
- `/api/adm/softwareList`
- `/api/adm/createSoftware`
- `/api/adm/updateSoftware`
- `/api/adm/authList`
- `/api/adm/createAuth`
- `/api/adm/commitUnBind`
- `/api/adm/exportTable`
- `/api/adm/customerList`
- `/api/adm/cloudVariablesList`
- `/api/adm/saveCloudVariables`
- `/api/adm/blackWhiteList`
- `/api/adm/saveBlackWhiteList`
- `/api/adm/message/event`
- `/api/adm/subUserList`

## 软件侧 API

软件客户端接口统一前缀为 `/api/client`。

完整接入流程和可运行示例见 [docs/client-integration.md](docs/client-integration.md)。推荐客户端只引入 SDK，并通过配置文件维护项目名、服务地址、软件 ID、实例密钥和版本号。

配置模板：

```text
clients/python/keydesk-client.example.json
```

最小 Python 示例：

```python
from clients.python import KeyDeskApp, KeyDeskError

app = KeyDeskApp.from_file("keydesk-client.json")

try:
    app.check_update()
    card = app.require_license()
    variables = app.cloud_variables()
except KeyDeskError as exc:
    print(f"授权失败: {exc}")
```

检查更新：

```http
POST /api/client/software/checkUpdate
```

```json
{
  "softwareId": "SWxxxx",
  "instanceKey": "IKxxxx",
  "version": "1.0.0",
  "macid": "DEVICE-001"
}
```

激活卡密：

```http
POST /api/client/auth/activate
```

```json
{
  "softwareId": "SWxxxx",
  "instanceKey": "IKxxxx",
  "authId": "KMxxxx",
  "macid": "DEVICE-001"
}
```

验证卡密：

```http
POST /api/client/auth/verify
```

```json
{
  "softwareId": "SWxxxx",
  "instanceKey": "IKxxxx",
  "authId": "KMxxxx",
  "macid": "DEVICE-001"
}
```

读取云变量：

```http
POST /api/client/cloudVariables/list
```

软件侧用户：

```http
POST /api/client/user/register
POST /api/client/user/login
POST /api/client/user/heartbeat
POST /api/client/user/logout
```

## 权限说明

角色权限按后台创建账号时分配：

- 超级管理员（开发者）：拥有全部权限，可以创建管理员和普通用户。
- 管理员：可以创建普通用户、管理实例，并为任意可见实例创建卡密。
- 普通用户：只能创建卡密，并查看被分配实例的数据。

主要权限码：

```text
softView, softCreate, softEdit, softDelete
authCreate, authDelete, authExport, authUnbind
userView
cloudVarView, cloudVarAdd, cloudVarDelete
blackWhiteView, blackWhiteAdd, blackWhiteDelete
```

子账户还可以限制可管理实例，支持指定实例 ID 或 `*` 表示全部实例。

## 测试

后端测试：

```bash
cd backend
pytest
```

前端构建：

```bash
cd frontend
npm install
npm run build
```

Docker 构建验证：

```bash
docker compose build
docker compose config
```

## 运维建议

- 生产环境务必修改 `CARD_SECRET_KEY` 和默认管理员密码。
- 建议使用 HTTPS，可以在 Nginx 前面再接入 Caddy、Traefik 或云厂商负载均衡。
- 定期备份 `runtime/mysql` 或使用 `mysqldump` 导出数据库。
- 不要把 `.env`、数据库文件、导出的卡密 CSV 提交到代码仓库。
