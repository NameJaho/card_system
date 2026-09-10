#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


SDK_VERSION = "1.0.0"


class KeyDeskError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "KEYDESK_ERROR",
        http_status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.http_status = http_status
        self.retryable = retryable


class KeyDeskConfigError(KeyDeskError):
    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="CONFIG_INVALID", retryable=False)


class KeyDeskNetworkError(KeyDeskError):
    pass


class LicenseError(KeyDeskError):
    pass


def _value(data: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return default


def _load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise KeyDeskConfigError(f"配置文件不存在: {path}")
    if path.suffix.lower() == ".json":
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise KeyDeskConfigError(f"JSON 配置格式错误: {exc}") from exc
    if path.suffix.lower() == ".toml":
        try:
            import tomllib
        except ModuleNotFoundError as exc:
            raise KeyDeskConfigError("当前 Python 版本不支持 TOML，请改用 JSON 配置") from exc
        return tomllib.loads(path.read_text(encoding="utf-8"))
    raise KeyDeskConfigError("配置文件只支持 .json 或 .toml")


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-.")
    return cleaned or "default"


def platform_data_dir(software_id: str) -> Path:
    app_name = _safe_component(software_id)
    if sys.platform == "win32":
        root = Path(os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or (Path.home() / "AppData" / "Local"))
        return root / "KeyDesk" / app_name
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "KeyDesk" / app_name
    root = Path(os.getenv("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return root / "keydesk" / app_name


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


@dataclass
class KeyDeskConfig:
    base_url: str
    software_id: str
    version: str
    project_name: str = "KeyDesk App"
    instance_key: str = ""
    auth_id: str = ""
    macid: str = ""
    timeout: int = 10
    max_retries: int = 2
    license_file: str = ""
    device_file: str = ""
    config_path: Path | None = field(default=None, repr=False)

    @classmethod
    def from_file(cls, path: str | Path = "keydesk.json") -> "KeyDeskConfig":
        config_path = Path(path).expanduser().resolve()
        config = cls.from_dict(_load_config_file(config_path))
        config.config_path = config_path
        return config

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeyDeskConfig":
        config = cls(
            base_url=str(_value(data, "baseUrl", "base_url")).strip(),
            software_id=str(_value(data, "softwareId", "software_id")).strip(),
            version=str(_value(data, "version")).strip(),
            project_name=str(_value(data, "projectName", "project_name", "name", default="KeyDesk App")).strip() or "KeyDesk App",
            instance_key=str(_value(data, "instanceKey", "instance_key", "privateKey", "private_key")).strip(),
            auth_id=str(_value(data, "authId", "auth_id")).strip(),
            macid=str(_value(data, "macid", "installationId", "installation_id")).strip(),
            timeout=max(1, int(_value(data, "timeout", default=10) or 10)),
            max_retries=max(0, min(5, int(_value(data, "maxRetries", "max_retries", default=2) or 0))),
            license_file=str(_value(data, "licenseFile", "license_file")).strip(),
            device_file=str(_value(data, "deviceFile", "device_file")).strip(),
        )
        config.validate()
        return config

    @property
    def base_dir(self) -> Path:
        return self.config_path.parent if self.config_path else Path.cwd()

    @property
    def state_dir(self) -> Path:
        return platform_data_dir(self.software_id)

    def resolve_path(self, value: str, default_name: str) -> Path:
        if not value:
            return self.state_dir / default_name
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.base_dir / path

    @property
    def license_path(self) -> Path:
        return self.resolve_path(self.license_file, "license.json")

    @property
    def device_path(self) -> Path:
        return self.resolve_path(self.device_file, "installation-id")

    def validate(self) -> None:
        missing = []
        if not self.base_url:
            missing.append("baseUrl")
        if not self.software_id:
            missing.append("softwareId")
        if not self.version:
            missing.append("version")
        if missing:
            raise KeyDeskConfigError(f"配置缺少必要字段: {', '.join(missing)}")
        if not self.base_url.lower().startswith(("http://", "https://")):
            raise KeyDeskConfigError("baseUrl 必须使用 http:// 或 https://")


@dataclass
class KeyDeskClient:
    base_url: str
    timeout: int = 10

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json;charset=UTF-8", "User-Agent": f"keydesk-python/{SDK_VERSION}"},
            method="POST",
        )
        status: int | None = None
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise KeyDeskNetworkError(
                f"授权服务网络不可达: {reason}",
                error_code="NETWORK_ERROR",
                retryable=True,
            ) from exc
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise KeyDeskNetworkError(
                "授权服务返回了无效 JSON",
                error_code="INVALID_RESPONSE",
                http_status=status,
                retryable=bool(status and status >= 500),
            ) from exc
        if not isinstance(result, dict):
            raise KeyDeskNetworkError(
                "授权服务响应格式无效",
                error_code="INVALID_RESPONSE",
                http_status=status,
                retryable=bool(status and status >= 500),
            )
        if not result.get("success"):
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            code = str(error.get("code") or "REQUEST_FAILED")
            message = str(error.get("message") or result.get("message") or "request failed")
            retryable = bool(error.get("retryable")) or bool(status and status >= 500)
            error_type = LicenseError if code.startswith(("LICENSE_", "INSTALLATION_")) else KeyDeskError
            raise error_type(message, error_code=code, http_status=status, retryable=retryable)
        return result

    @staticmethod
    def _payload(payload: dict[str, Any], instance_key: str = "") -> dict[str, Any]:
        if instance_key:
            payload["instanceKey"] = instance_key
        return payload

    def validate_license(self, software_id: str, license_key: str, installation_id: str, client_version: str) -> dict[str, Any]:
        return self._post(
            "/api/client/v1/license/validate",
            {"softwareId": software_id, "licenseKey": license_key, "installationId": installation_id, "clientVersion": client_version},
        )

    # Legacy protocol methods remain for migration tools only.
    def check_update(self, software_id: str, version: str, macid: str = "", instance_key: str = "") -> dict[str, Any]:
        return self._post("/api/client/software/checkUpdate", self._payload({"softwareId": software_id, "version": version, "macid": macid}, instance_key))

    def activate(self, software_id: str, auth_id: str, macid: str, instance_key: str = "") -> dict[str, Any]:
        return self._post("/api/client/auth/activate", self._payload({"softwareId": software_id, "authId": auth_id, "macid": macid}, instance_key))

    def verify(self, software_id: str, auth_id: str, macid: str, instance_key: str = "") -> dict[str, Any]:
        return self._post("/api/client/auth/verify", self._payload({"softwareId": software_id, "authId": auth_id, "macid": macid}, instance_key))

    def unbind(self, software_id: str, auth_id: str, macid: str, instance_key: str = "") -> dict[str, Any]:
        return self._post("/api/client/auth/unbind", self._payload({"softwareId": software_id, "authId": auth_id, "macid": macid}, instance_key))

    def cloud_variables(self, software_id: str, instance_key: str = "") -> dict[str, Any]:
        return self._post("/api/client/cloudVariables/list", self._payload({"softwareId": software_id}, instance_key))


class KeyDeskApp:
    def __init__(self, config: KeyDeskConfig):
        self.config = config
        self.client = KeyDeskClient(config.base_url, timeout=config.timeout)

    @classmethod
    def from_file(cls, path: str | Path = "keydesk.json") -> "KeyDeskApp":
        return cls(KeyDeskConfig.from_file(path))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeyDeskApp":
        return cls(KeyDeskConfig.from_dict(data))

    @property
    def installation_id(self) -> str:
        if self.config.macid:
            return self.config.macid
        path = self.config.device_path
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        value = f"INST-{uuid.uuid4().hex.upper()}"
        _write_private(path, value)
        return value

    @property
    def macid(self) -> str:
        return self.installation_id

    def _state(self) -> dict[str, Any]:
        path = self.config.license_path
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_state(self, data: dict[str, Any]) -> None:
        current = self._state()
        current.update(data)
        _write_private(self.config.license_path, json.dumps(current, ensure_ascii=False, indent=2))

    def saved_auth_id(self) -> str:
        state = self._state()
        return str(state.get("licenseKey") or state.get("authId") or self.config.auth_id or "").strip()

    def save_license(self, license_key: str, result: dict[str, Any]) -> None:
        self._save_state(
            {
                "softwareId": self.config.software_id,
                "licenseKey": license_key,
                "status": result.get("status"),
                "expiresAt": result.get("expiresAt"),
                "lastServerTime": result.get("serverTime"),
                "requiresOnline": True,
            }
        )

    def _license_key(self, auth_id: str | None, prompt: Callable[[], str] | None = None) -> str:
        value = str(auth_id or self.saved_auth_id()).strip()
        if not value and prompt:
            value = str(prompt() or "").strip()
        if not value:
            raise KeyDeskConfigError("缺少卡密，请传入卡密或提供 prompt 回调")
        return value

    def require_license(self, auth_id: str | None = None, *, prompt: Callable[[], str] | None = None) -> dict[str, Any]:
        license_key = self._license_key(auth_id, prompt)
        last_error: KeyDeskError | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                result = self.client.validate_license(self.config.software_id, license_key, self.installation_id, self.config.version)["data"]
                if result.get("status") != "active":
                    raise LicenseError("授权状态无效", error_code="LICENSE_INVALID_STATE")
                self.save_license(license_key, result)
                return result
            except KeyDeskError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.config.max_retries:
                    raise
                time.sleep(0.25 * (2**attempt))
        assert last_error is not None
        raise last_error

    # Compatibility names now use the single idempotent v1 endpoint.
    def activate(self, auth_id: str | None = None, save: bool = True) -> dict[str, Any]:
        return self.require_license(auth_id)

    def verify(self, auth_id: str | None = None, save: bool = True) -> dict[str, Any]:
        return self.require_license(auth_id)

    def check_update(self, version: str | None = None) -> dict[str, Any]:
        if version and version != self.config.version:
            original = self.config.version
            self.config.version = version
            try:
                return self.require_license()
            finally:
                self.config.version = original
        return self.require_license()

    def unbind(self, auth_id: str | None = None) -> dict[str, Any]:
        if not self.config.instance_key:
            raise KeyDeskConfigError("v1 不允许客户端隐式解绑，请在后台执行显式解绑")
        license_key = self._license_key(auth_id)
        return self.client.unbind(self.config.software_id, license_key, self.installation_id, self.config.instance_key)["data"]

    def cloud_variables(self, as_dict: bool = True) -> dict[str, str] | list[dict[str, Any]]:
        if not self.config.instance_key:
            raise KeyDeskConfigError("读取旧版云变量需要迁移期 instanceKey")
        rows = self.client.cloud_variables(self.config.software_id, self.config.instance_key)["data"]
        if not as_dict:
            return rows
        return {str(row.get("key")): str(row.get("value") or "") for row in rows if row.get("key")}


KeyDesk = KeyDeskApp


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyDesk Python SDK")
    parser.add_argument("--config", default="keydesk.json", help="仅包含 baseUrl/softwareId/version 的配置文件")
    parser.add_argument("--auth-id", default="", help="卡密；省略时读取本地安全状态文件")
    parser.add_argument("command", choices=["validate", "require-license"], nargs="?", default="validate")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        print_json(KeyDeskApp.from_file(args.config).require_license(args.auth_id or None))
    except KeyDeskError as exc:
        print(f"error [{exc.error_code}]: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
