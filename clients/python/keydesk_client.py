#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import platform
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class KeyDeskError(RuntimeError):
    pass


class KeyDeskConfigError(KeyDeskError):
    pass


def _value(data: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return default


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise KeyDeskConfigError(f"配置文件不存在: {path}")
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".toml":
        try:
            import tomllib
        except ModuleNotFoundError as exc:
            raise KeyDeskConfigError("当前 Python 版本不支持 TOML，请改用 JSON 配置") from exc
        return tomllib.loads(path.read_text(encoding="utf-8"))
    raise KeyDeskConfigError("配置文件只支持 .json 或 .toml")


def default_machine_id(project_name: str) -> str:
    raw = "|".join(
        [
            project_name,
            platform.system(),
            platform.machine(),
            platform.node(),
            getpass.getuser(),
            str(uuid.getnode()),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    return f"KD-{digest[:24]}"


@dataclass
class KeyDeskConfig:
    project_name: str
    base_url: str
    software_id: str
    instance_key: str
    version: str = "1.0.0"
    auth_id: str = ""
    macid: str = ""
    timeout: int = 10
    license_file: str = ".keydesk-license.json"
    device_file: str = ".keydesk-device"
    heartbeat_interval: int = 60
    auto_activate: bool = True
    allow_missing_instance_key: bool = False
    config_path: Path | None = field(default=None, repr=False)

    @classmethod
    def from_file(cls, path: str | Path = "keydesk-client.json") -> "KeyDeskConfig":
        config_path = Path(path).expanduser().resolve()
        data = _load_config_file(config_path)
        config = cls.from_dict(data)
        config.config_path = config_path
        return config

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeyDeskConfig":
        config = cls(
            project_name=str(_value(data, "projectName", "project_name", "name")).strip(),
            base_url=str(_value(data, "baseUrl", "base_url")).strip(),
            software_id=str(_value(data, "softwareId", "software_id")).strip(),
            instance_key=str(_value(data, "instanceKey", "instance_key", "privateKey", "private_key")).strip(),
            version=str(_value(data, "version", default="1.0.0")).strip() or "1.0.0",
            auth_id=str(_value(data, "authId", "auth_id", default="")).strip(),
            macid=str(_value(data, "macid", "deviceId", "device_id", default="")).strip(),
            timeout=int(_value(data, "timeout", default=10) or 10),
            license_file=str(_value(data, "licenseFile", "license_file", default=".keydesk-license.json")),
            device_file=str(_value(data, "deviceFile", "device_file", default=".keydesk-device")),
            heartbeat_interval=int(_value(data, "heartbeatInterval", "heartbeat_interval", default=60) or 60),
            auto_activate=_bool_value(_value(data, "autoActivate", "auto_activate", default=True), default=True),
            allow_missing_instance_key=_bool_value(
                _value(data, "allowMissingInstanceKey", "allow_missing_instance_key", default=False),
                default=False,
            ),
        )
        config.validate()
        return config

    @property
    def base_dir(self) -> Path:
        if self.config_path:
            return self.config_path.parent
        return Path.cwd()

    def resolve_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return self.base_dir / path

    @property
    def license_path(self) -> Path:
        return self.resolve_path(self.license_file)

    @property
    def device_path(self) -> Path:
        return self.resolve_path(self.device_file)

    def validate(self) -> None:
        missing = []
        if not self.project_name:
            missing.append("projectName")
        if not self.base_url:
            missing.append("baseUrl")
        if not self.software_id:
            missing.append("softwareId")
        if not self.instance_key and not self.allow_missing_instance_key:
            missing.append("instanceKey")
        if missing:
            raise KeyDeskConfigError(f"配置缺少必要字段: {', '.join(missing)}")


@dataclass
class KeyDeskClient:
    base_url: str
    timeout: int = 10

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json;charset=UTF-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise KeyDeskError(f"HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise KeyDeskError(f"Network error: {exc.reason}") from exc
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise KeyDeskError(f"Invalid JSON response: {raw[:200]}") from exc
        if not result.get("success"):
            raise KeyDeskError(result.get("message") or "request failed")
        return result

    @staticmethod
    def _payload(payload: dict[str, Any], instance_key: str = "") -> dict[str, Any]:
        if instance_key:
            payload["instanceKey"] = instance_key
        return payload

    def check_update(self, software_id: str, version: str, macid: str = "", instance_key: str = "") -> dict[str, Any]:
        return self._post(
            "/api/client/software/checkUpdate",
            self._payload({"softwareId": software_id, "version": version, "macid": macid}, instance_key),
        )

    def activate(self, software_id: str, auth_id: str, macid: str, instance_key: str = "") -> dict[str, Any]:
        return self._post(
            "/api/client/auth/activate",
            self._payload({"softwareId": software_id, "authId": auth_id, "macid": macid}, instance_key),
        )

    def verify(self, software_id: str, auth_id: str, macid: str, instance_key: str = "") -> dict[str, Any]:
        return self._post(
            "/api/client/auth/verify",
            self._payload({"softwareId": software_id, "authId": auth_id, "macid": macid}, instance_key),
        )

    def unbind(self, software_id: str, auth_id: str, macid: str, instance_key: str = "") -> dict[str, Any]:
        return self._post(
            "/api/client/auth/unbind",
            self._payload({"softwareId": software_id, "authId": auth_id, "macid": macid}, instance_key),
        )

    def cloud_variables(self, software_id: str, instance_key: str = "") -> dict[str, Any]:
        return self._post("/api/client/cloudVariables/list", self._payload({"softwareId": software_id}, instance_key))

    def register_user(self, software_id: str, email: str, password: str, nick_name: str = "", instance_key: str = "") -> dict[str, Any]:
        return self._post(
            "/api/client/user/register",
            self._payload({"softwareId": software_id, "email": email, "password": password, "nickName": nick_name or email}, instance_key),
        )

    def login_user(self, software_id: str, email: str, password: str, instance_key: str = "") -> dict[str, Any]:
        return self._post("/api/client/user/login", self._payload({"softwareId": software_id, "email": email, "password": password}, instance_key))

    def heartbeat(self, software_id: str, customer_id: str = "", macid: str = "", instance_key: str = "") -> dict[str, Any]:
        return self._post(
            "/api/client/user/heartbeat",
            self._payload({"softwareId": software_id, "customerId": customer_id, "macid": macid}, instance_key),
        )

    def logout_user(self, software_id: str, customer_id: str = "", instance_key: str = "") -> dict[str, Any]:
        return self._post("/api/client/user/logout", self._payload({"softwareId": software_id, "customerId": customer_id}, instance_key))


class KeyDeskApp:
    def __init__(self, config: KeyDeskConfig):
        self.config = config
        self.client = KeyDeskClient(config.base_url, timeout=config.timeout)

    @classmethod
    def from_file(cls, path: str | Path = "keydesk-client.json") -> "KeyDeskApp":
        return cls(KeyDeskConfig.from_file(path))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeyDeskApp":
        return cls(KeyDeskConfig.from_dict(data))

    @property
    def macid(self) -> str:
        if self.config.macid:
            return self.config.macid
        path = self.config.device_path
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        value = default_machine_id(self.config.project_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return value

    def _state(self) -> dict[str, Any]:
        path = self.config.license_path
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_state(self, data: dict[str, Any]) -> None:
        path = self.config.license_path
        path.parent.mkdir(parents=True, exist_ok=True)
        current = self._state()
        current.update(data)
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")

    def saved_auth_id(self) -> str:
        return str(self._state().get("authId") or self.config.auth_id or "").strip()

    def save_license(self, auth_id: str, card: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"projectName": self.config.project_name, "softwareId": self.config.software_id, "authId": auth_id}
        if card:
            payload["card"] = card
            if card.get("endTime"):
                payload["endTime"] = card["endTime"]
        self._save_state(payload)

    def check_update(self, version: str | None = None) -> dict[str, Any]:
        result = self.client.check_update(self.config.software_id, version or self.config.version, self.macid, self.config.instance_key)
        return result["data"]

    def activate(self, auth_id: str | None = None, save: bool = True) -> dict[str, Any]:
        value = (auth_id or self.saved_auth_id()).strip()
        if not value:
            raise KeyDeskConfigError("缺少卡密，请传入 auth_id 或在配置文件/授权文件中保存 authId")
        result = self.client.activate(self.config.software_id, value, self.macid, self.config.instance_key)
        card = result["data"]
        if save:
            self.save_license(value, card)
        return card

    def verify(self, auth_id: str | None = None, save: bool = True) -> dict[str, Any]:
        value = (auth_id or self.saved_auth_id()).strip()
        if not value:
            raise KeyDeskConfigError("缺少卡密，请传入 auth_id 或在配置文件/授权文件中保存 authId")
        result = self.client.verify(self.config.software_id, value, self.macid, self.config.instance_key)
        card = result["data"]
        if save:
            self.save_license(value, card)
        return card

    def require_license(self, auth_id: str | None = None) -> dict[str, Any]:
        try:
            return self.verify(auth_id)
        except KeyDeskError:
            if not self.config.auto_activate:
                raise
            value = (auth_id or self.saved_auth_id()).strip()
            if not value:
                raise
            return self.activate(value)

    def unbind(self, auth_id: str | None = None) -> dict[str, Any]:
        value = (auth_id or self.saved_auth_id()).strip()
        if not value:
            raise KeyDeskConfigError("缺少卡密，无法解绑")
        return self.client.unbind(self.config.software_id, value, self.macid, self.config.instance_key)["data"]

    def cloud_variables(self, as_dict: bool = True) -> dict[str, str] | list[dict[str, Any]]:
        rows = self.client.cloud_variables(self.config.software_id, self.config.instance_key)["data"]
        if not as_dict:
            return rows
        return {str(row.get("key")): str(row.get("value") or "") for row in rows if row.get("key")}

    def register_user(self, email: str, password: str, nick_name: str = "") -> dict[str, Any]:
        return self.client.register_user(self.config.software_id, email, password, nick_name, self.config.instance_key)["data"]

    def login_user(self, email: str, password: str, save: bool = True) -> dict[str, Any]:
        customer = self.client.login_user(self.config.software_id, email, password, self.config.instance_key)["data"]
        if save and customer.get("customerId"):
            self._save_state({"customerId": customer["customerId"], "customerEmail": email})
        return customer

    def heartbeat(self, customer_id: str = "") -> dict[str, Any]:
        value = customer_id or str(self._state().get("customerId") or "")
        return self.client.heartbeat(self.config.software_id, value, self.macid, self.config.instance_key)["data"]

    def logout_user(self, customer_id: str = "") -> dict[str, Any]:
        value = customer_id or str(self._state().get("customerId") or "")
        return self.client.logout_user(self.config.software_id, value, self.config.instance_key)["data"]

    def heartbeat_loop(self, customer_id: str = "", interval: int | None = None) -> None:
        delay = interval or self.config.heartbeat_interval
        while True:
            self.heartbeat(customer_id)
            time.sleep(delay)


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def run_config_command(app: KeyDeskApp, args: argparse.Namespace) -> None:
    if args.command == "check-update":
        print_json(app.check_update(args.version or None))
    elif args.command in {"activate", "bind-license"}:
        print_json(app.activate(args.auth_id or None))
    elif args.command == "verify":
        print_json(app.verify(args.auth_id or None))
    elif args.command == "require-license":
        print_json(app.require_license(args.auth_id or None))
    elif args.command == "unbind":
        print_json(app.unbind(args.auth_id or None))
    elif args.command == "vars":
        print_json(app.cloud_variables(as_dict=not args.raw_vars))
    elif args.command == "register":
        print_json(app.register_user(args.email, args.password, args.nick_name))
    elif args.command == "login":
        print_json(app.login_user(args.email, args.password))
    elif args.command == "heartbeat":
        while True:
            print_json(app.heartbeat(args.customer_id))
            if args.interval <= 0:
                break
            time.sleep(args.interval)
    elif args.command == "logout":
        print_json(app.logout_user(args.customer_id))
    elif args.command == "demo":
        print("1. check update")
        print_json(app.check_update(args.version or None))
        if args.auth_id or app.saved_auth_id():
            print("2. require license")
            print_json(app.require_license(args.auth_id or None))
        print("3. cloud variables")
        print_json(app.cloud_variables())


def run_legacy_command(client: KeyDeskClient, args: argparse.Namespace) -> None:
    if args.command == "check-update":
        print_json(client.check_update(args.software_id, args.version, args.macid, args.instance_key))
    elif args.command in {"activate", "bind-license"}:
        print_json(client.activate(args.software_id, args.auth_id, args.macid, args.instance_key))
    elif args.command in {"verify", "require-license"}:
        print_json(client.verify(args.software_id, args.auth_id, args.macid, args.instance_key))
    elif args.command == "unbind":
        print_json(client.unbind(args.software_id, args.auth_id, args.macid, args.instance_key))
    elif args.command == "vars":
        print_json(client.cloud_variables(args.software_id, args.instance_key))
    elif args.command == "register":
        print_json(client.register_user(args.software_id, args.email, args.password, args.nick_name, args.instance_key))
    elif args.command == "login":
        print_json(client.login_user(args.software_id, args.email, args.password, args.instance_key))
    elif args.command == "heartbeat":
        while True:
            print_json(client.heartbeat(args.software_id, args.customer_id, args.macid, args.instance_key))
            if args.interval <= 0:
                break
            time.sleep(args.interval)
    elif args.command == "logout":
        print_json(client.logout_user(args.software_id, args.customer_id, args.instance_key))
    elif args.command == "demo":
        print("1. check update")
        print_json(client.check_update(args.software_id, args.version, args.macid, args.instance_key))
        if args.auth_id:
            print("2. verify license")
            print_json(client.verify(args.software_id, args.auth_id, args.macid, args.instance_key))
        print("3. cloud variables")
        print_json(client.cloud_variables(args.software_id, args.instance_key))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyDesk client SDK and CLI")

    def add_common_options(target: argparse.ArgumentParser, *, defaults: bool) -> None:
        string_default = "" if defaults else argparse.SUPPRESS
        interval_default: int | str = 0 if defaults else argparse.SUPPRESS
        raw_vars_default: bool | str = False if defaults else argparse.SUPPRESS
        target.add_argument("--config", default=string_default, help="配置文件路径，例如 keydesk-client.json")
        target.add_argument("--base-url", default=string_default, help="兼容旧用法：服务地址，例如 http://127.0.0.1:8080")
        target.add_argument("--software-id", default=string_default, help="兼容旧用法：后台实例 ID")
        target.add_argument("--instance-key", default=string_default, help="兼容旧用法：实例密钥")
        target.add_argument("--auth-id", default=string_default, help="卡密，activate/verify/unbind 需要")
        target.add_argument("--macid", default=("DEMO-MACHINE-1" if defaults else argparse.SUPPRESS), help="兼容旧用法：客户端设备码")
        target.add_argument("--version", default=string_default, help="当前客户端版本；配置模式为空时使用配置文件版本")
        target.add_argument("--email", default=string_default, help="软件侧用户邮箱")
        target.add_argument("--password", default=string_default, help="软件侧用户密码")
        target.add_argument("--nick-name", default=string_default, help="软件侧用户昵称")
        target.add_argument("--customer-id", default=string_default, help="软件侧用户编号，heartbeat/logout 可直接传")
        target.add_argument("--interval", type=int, default=interval_default, help="heartbeat 循环间隔秒数，0 表示只执行一次")
        target.add_argument("--raw-vars", action="store_true", default=raw_vars_default, help="配置模式读取云变量时返回原始列表")

    add_common_options(parser, defaults=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in [
        "check-update",
        "activate",
        "bind-license",
        "verify",
        "require-license",
        "unbind",
        "vars",
        "register",
        "login",
        "heartbeat",
        "logout",
        "demo",
    ]:
        subparser = subparsers.add_parser(command)
        add_common_options(subparser, defaults=False)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.config:
            run_config_command(KeyDeskApp.from_file(args.config), args)
            return 0
        if not args.base_url or not args.software_id:
            parser.error("未使用 --config 时必须提供 --base-url 和 --software-id")
        if args.command in {"activate", "bind-license", "verify", "require-license", "unbind"} and not args.auth_id:
            parser.error(f"{args.command} 需要 --auth-id")
        version = args.version or "1.0.0"
        args.version = version
        run_legacy_command(KeyDeskClient(args.base_url), args)
    except KeyDeskError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
