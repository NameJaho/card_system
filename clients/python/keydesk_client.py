#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


SDK_VERSION = "2.0.0"
BUILTIN_PRODUCTION_BASE_URL = ""
BUILTIN_TRUSTED_LICENSE_KEYS: dict[str, str] = {}


class KeyDeskError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "KEYDESK_ERROR",
        http_status: int | None = None,
        retryable: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.http_status = http_status
        self.retryable = retryable
        self.request_id = request_id


class KeyDeskConfigError(KeyDeskError):
    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="CONFIG_INVALID", retryable=False)


class KeyDeskNetworkError(KeyDeskError):
    pass


class LicenseError(KeyDeskError):
    pass


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str, expected_length: int | None = None) -> bytes:
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64url")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _b64url_encode(raw) != value:
        raise ValueError("non-canonical base64url")
    if expected_length is not None and len(raw) != expected_length:
        raise ValueError("invalid decoded length")
    return raw


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
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise KeyDeskConfigError(f"JSON 配置格式错误: {exc}") from exc
    elif path.suffix.lower() == ".toml":
        try:
            import tomllib
        except ModuleNotFoundError as exc:
            raise KeyDeskConfigError("当前 Python 版本不支持 TOML，请使用 JSON 配置") from exc
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    else:
        raise KeyDeskConfigError("配置文件只支持 .json 或 .toml")
    if not isinstance(value, dict):
        raise KeyDeskConfigError("配置文件根节点必须是对象")
    return value


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


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(value: bytes, *, protect: bool) -> bytes:
    if sys.platform != "win32":
        return value
    source_buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    blob_pointer = ctypes.POINTER(_DataBlob)
    crypt32.CryptProtectData.argtypes = [blob_pointer, ctypes.c_void_p, blob_pointer, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, blob_pointer]
    crypt32.CryptProtectData.restype = ctypes.c_int
    crypt32.CryptUnprotectData.argtypes = [blob_pointer, ctypes.c_void_p, blob_pointer, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, blob_pointer]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    if protect:
        success = crypt32.CryptProtectData(ctypes.byref(source), None, None, None, None, 0x4, ctypes.byref(output))
    else:
        success = crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output))
    if not success:
        raise OSError("Windows DPAPI operation failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def _write_secret(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"KEYDESK-DPAPI-V2\0" + _dpapi(value, protect=True) if sys.platform == "win32" else b"KEYDESK-FILE-V2\0" + value
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_bytes(payload)
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_secret(path: Path) -> bytes:
    payload = path.read_bytes()
    if payload.startswith(b"KEYDESK-DPAPI-V2\0"):
        return _dpapi(payload[len(b"KEYDESK-DPAPI-V2\0"):], protect=False)
    if payload.startswith(b"KEYDESK-FILE-V2\0"):
        return payload[len(b"KEYDESK-FILE-V2\0"):]
    return payload


@dataclass(frozen=True)
class DeviceIdentity:
    installation_id: str
    private_key: Ed25519PrivateKey = field(repr=False)

    @property
    def public_key_b64(self) -> str:
        raw = self.private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return _b64url_encode(raw)

    @property
    def thumbprint(self) -> str:
        return hashlib.sha256(_b64url_decode(self.public_key_b64, 32)).hexdigest()

    def sign(self, message: bytes) -> str:
        return _b64url_encode(self.private_key.sign(message))


def _canonical_device_message(
    software_id: str,
    license_key: str,
    installation_id: str,
    client_version: str,
    device_public_key: str,
    request_nonce: str,
    request_time: str,
) -> bytes:
    license_hash = hashlib.sha256(license_key.strip().upper().encode("utf-8")).hexdigest()
    fields = (
        "KEYDESK-LICENSE-V2",
        software_id,
        license_hash,
        installation_id,
        client_version,
        device_public_key,
        request_nonce,
        request_time,
    )
    if any("\n" in value or "\r" in value for value in fields):
        raise KeyDeskConfigError("授权字段不能包含换行符")
    return "\n".join(fields).encode("utf-8")


@dataclass
class KeyDeskConfig:
    base_url: str
    software_id: str
    version: str
    project_name: str = "KeyDesk App"
    auth_id: str = ""
    timeout: int = 10
    max_retries: int = 2
    license_file: str = ""
    device_file: str = ""
    trusted_public_keys: dict[str, str] = field(default_factory=dict, repr=False)
    config_path: Path | None = field(default=None, repr=False)

    @classmethod
    def from_file(cls, path: str | Path = "keydesk.json") -> "KeyDeskConfig":
        config_path = Path(path).expanduser().resolve()
        config = cls.from_dict(_load_config_file(config_path))
        config.config_path = config_path
        return config

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeyDeskConfig":
        keys = _value(data, "trustedPublicKeys", "trusted_public_keys", default={})
        if not isinstance(keys, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in keys.items()):
            raise KeyDeskConfigError("trustedPublicKeys 必须是 kid 到 Ed25519 公钥的对象")
        config = cls(
            base_url=str(_value(data, "baseUrl", "base_url")).strip(),
            software_id=str(_value(data, "softwareId", "software_id")).strip(),
            version=str(_value(data, "version")).strip(),
            project_name=str(_value(data, "projectName", "project_name", "name", default="KeyDesk App")).strip() or "KeyDesk App",
            auth_id=str(_value(data, "authId", "auth_id", "licenseKey", "license_key")).strip(),
            timeout=max(1, int(_value(data, "timeout", default=10) or 10)),
            max_retries=max(0, min(5, int(_value(data, "maxRetries", "max_retries", default=2) or 0))),
            license_file=str(_value(data, "licenseFile", "license_file")).strip(),
            device_file=str(_value(data, "deviceFile", "device_file")).strip(),
            trusted_public_keys=dict(keys),
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
        return self.resolve_path(self.license_file, "license-v2.bin")

    @property
    def device_path(self) -> Path:
        return self.resolve_path(self.device_file, "device-v2.bin")

    @property
    def effective_base_url(self) -> str:
        return (BUILTIN_PRODUCTION_BASE_URL or self.base_url).rstrip("/")

    @property
    def effective_trusted_keys(self) -> dict[str, str]:
        return dict(BUILTIN_TRUSTED_LICENSE_KEYS or self.trusted_public_keys)

    def validate(self) -> None:
        missing = []
        if not self.base_url and not BUILTIN_PRODUCTION_BASE_URL:
            missing.append("baseUrl")
        if not self.software_id:
            missing.append("softwareId")
        if not self.version:
            missing.append("version")
        if missing:
            raise KeyDeskConfigError(f"配置缺少必要字段: {', '.join(missing)}")
        if not self.effective_base_url.lower().startswith("https://"):
            raise KeyDeskConfigError("v2 授权地址必须使用 HTTPS")
        for public_key in self.effective_trusted_keys.values():
            try:
                _b64url_decode(public_key, 32)
            except ValueError as exc:
                raise KeyDeskConfigError("trustedPublicKeys 包含无效 Ed25519 公钥") from exc


@dataclass
class KeyDeskClient:
    base_url: str
    timeout: int = 10
    trusted_public_keys: dict[str, str] = field(default_factory=dict, repr=False)

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
            error_type = LicenseError if code.startswith(("LICENSE_", "DEVICE_", "LEASE_", "CLIENT_", "PROTOCOL_")) else KeyDeskError
            raise error_type(
                message,
                error_code=code,
                http_status=status,
                retryable=retryable,
                request_id=str(error.get("requestId") or "") or None,
            )
        return result

    def _verify_lease(
        self,
        result: dict[str, Any],
        software_id: str,
        installation_id: str,
        device_thumbprint: str,
        client_version: str,
    ) -> dict[str, Any]:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        token = data.get("leaseToken")
        if not isinstance(token, str) or not token:
            raise LicenseError("授权响应缺少官方签名 lease", error_code="LEASE_SIGNATURE_INVALID")
        try:
            encoded_header, encoded_claims, encoded_signature = token.split(".")
            header = json.loads(_b64url_decode(encoded_header))
            claims = json.loads(_b64url_decode(encoded_claims))
            if not isinstance(header, dict) or not isinstance(claims, dict):
                raise ValueError("invalid JWS objects")
            if header.get("alg") != "EdDSA" or header.get("typ") != "JWT":
                raise ValueError("unexpected JWS algorithm")
            kid = str(header.get("kid") or "")
            public_key_b64 = self.trusted_public_keys.get(kid)
            if not public_key_b64:
                raise ValueError("untrusted kid")
            public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(public_key_b64, 32))
            public_key.verify(_b64url_decode(encoded_signature, 64), f"{encoded_header}.{encoded_claims}".encode("ascii"))
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, InvalidSignature) as exc:
            raise LicenseError("授权 lease 签名无效", error_code="LEASE_SIGNATURE_INVALID") from exc

        now = int(time.time())
        expected_claims = {
            "iss": self.base_url.rstrip("/"),
            "aud": software_id,
            "installationId": installation_id,
            "deviceKeyThumbprint": device_thumbprint,
            "clientVersion": client_version,
            "status": "active",
            "protocolVersion": 2,
        }
        try:
            if any(claims.get(key) != value for key, value in expected_claims.items()):
                raise ValueError("claim mismatch")
            if not isinstance(claims.get("sub"), str) or not claims["sub"]:
                raise ValueError("missing subject")
            if not isinstance(claims.get("jti"), str) or not claims["jti"]:
                raise ValueError("missing jti")
            if not isinstance(claims.get("iat"), int) or not isinstance(claims.get("nbf"), int) or not isinstance(claims.get("exp"), int):
                raise ValueError("invalid NumericDate")
            if claims["exp"] <= now - 5 or claims["nbf"] > now + 5 or claims["iat"] > now + 120:
                raise ValueError("lease time invalid")
            if claims["nbf"] < claims["iat"] or claims["exp"] <= claims["nbf"] or claims["exp"] - claims["iat"] > 900:
                raise ValueError("lease lifetime invalid")
            for name in ("status", "updateAvailable", "updateRequired", "latestVersion", "minimumVersion"):
                if data.get(name) != claims.get(name):
                    raise ValueError(f"outer field mismatch: {name}")
            lease_expires = datetime.fromisoformat(str(data.get("leaseExpiresAt") or "").replace("Z", "+00:00"))
            if abs(int(lease_expires.timestamp()) - claims["exp"]) > 1:
                raise ValueError("lease expiry mismatch")
        except (ValueError, TypeError) as exc:
            raise LicenseError("授权 lease 声明不匹配", error_code="LEASE_CLAIMS_INVALID") from exc
        return claims

    def validate_license(
        self,
        software_id: str,
        license_key: str,
        installation_id: str,
        client_version: str,
        device_identity: DeviceIdentity | None = None,
    ) -> dict[str, Any]:
        device_identity = device_identity or DeviceIdentity(installation_id, Ed25519PrivateKey.generate())
        request_time = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        request_nonce = _b64url_encode(secrets.token_bytes(32))
        device_public_key = device_identity.public_key_b64
        message = _canonical_device_message(
            software_id,
            license_key,
            installation_id,
            client_version,
            device_public_key,
            request_nonce,
            request_time,
        )
        payload = {
            "protocolVersion": 2,
            "softwareId": software_id,
            "licenseKey": license_key,
            "installationId": installation_id,
            "clientVersion": client_version,
            "devicePublicKey": device_public_key,
            "requestNonce": request_nonce,
            "requestTime": request_time,
            "deviceSignature": device_identity.sign(message),
        }
        result = self._post("/api/client/v2/license/validate", payload)
        self._verify_lease(result, software_id, installation_id, device_identity.thumbprint, client_version)
        return result


class KeyDeskApp:
    def __init__(self, config: KeyDeskConfig):
        self.config = config
        self.client = KeyDeskClient(config.effective_base_url, timeout=config.timeout, trusted_public_keys=config.effective_trusted_keys)
        self._device_identity_cache: DeviceIdentity | None = None

    @classmethod
    def from_file(cls, path: str | Path = "keydesk.json") -> "KeyDeskApp":
        return cls(KeyDeskConfig.from_file(path))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeyDeskApp":
        return cls(KeyDeskConfig.from_dict(data))

    @property
    def device_identity(self) -> DeviceIdentity:
        if self._device_identity_cache:
            return self._device_identity_cache
        path = self.config.device_path
        installation_id = ""
        private_key: Ed25519PrivateKey | None = None
        if path.exists():
            load_error: Exception | None = None
            try:
                value = json.loads(_read_secret(path).decode("utf-8"))
                if isinstance(value, dict):
                    installation_id = str(value.get("installationId") or "").strip()
                    private_raw = _b64url_decode(str(value.get("devicePrivateKey") or ""), 32)
                    private_key = Ed25519PrivateKey.from_private_bytes(private_raw)
                if not installation_id.startswith("INST-"):
                    raise ValueError("invalid installation id")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
                load_error = exc
                try:
                    legacy = path.read_text(encoding="utf-8").strip()
                    if legacy.startswith("INST-"):
                        installation_id = legacy
                except (OSError, UnicodeDecodeError):
                    pass
            if private_key is None and not installation_id:
                raise KeyDeskConfigError(f"设备身份文件损坏，已停止运行以避免丢失原设备密钥: {path}") from load_error
        installation_id = installation_id or f"INST-{uuid.uuid4().hex.upper()}"
        private_key = private_key or Ed25519PrivateKey.generate()
        private_raw = private_key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        _write_secret(
            path,
            json.dumps(
                {"installationId": installation_id, "devicePrivateKey": _b64url_encode(private_raw)},
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        self._device_identity_cache = DeviceIdentity(installation_id, private_key)
        return self._device_identity_cache

    @property
    def installation_id(self) -> str:
        return self.device_identity.installation_id

    @property
    def macid(self) -> str:
        return self.installation_id

    def _state(self) -> dict[str, Any]:
        path = self.config.license_path
        if not path.exists():
            return {}
        try:
            value = json.loads(_read_secret(path).decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {}

    def _save_state(self, data: dict[str, Any]) -> None:
        current = self._state()
        current.update(data)
        _write_secret(self.config.license_path, json.dumps(current, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def saved_auth_id(self) -> str:
        state = self._state()
        return str(state.get("licenseKey") or self.config.auth_id or "").strip()

    def save_license(self, license_key: str, result: dict[str, Any]) -> None:
        self._save_state(
            {
                "softwareId": self.config.software_id,
                "licenseKey": license_key,
                "status": result.get("status"),
                "expiresAt": result.get("expiresAt"),
                "lastServerTime": result.get("serverTime"),
                "deviceKeyThumbprint": self.device_identity.thumbprint,
                "requiresOnline": True,
            }
        )

    def _clear_valid_state(self) -> None:
        state = self._state()
        if state:
            state["status"] = "invalid"
            state.pop("lastServerTime", None)
            _write_secret(self.config.license_path, json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def _license_key(self, auth_id: str | None, prompt: Callable[[], str] | None = None) -> str:
        value = str(auth_id or self.saved_auth_id()).strip()
        if not value and prompt:
            value = str(prompt() or "").strip()
        if not value:
            raise KeyDeskConfigError("缺少卡密，请传入卡密或提供 prompt 回调")
        return value

    def require_license(self, auth_id: str | None = None, *, prompt: Callable[[], str] | None = None) -> dict[str, Any]:
        license_key = self._license_key(auth_id, prompt)
        if not self.client.trusted_public_keys:
            raise KeyDeskConfigError("SDK 未内置或配置官方 Ed25519 公钥")
        last_error: KeyDeskError | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                result = self.client.validate_license(
                    self.config.software_id,
                    license_key,
                    self.installation_id,
                    self.config.version,
                    self.device_identity,
                )["data"]
                if result.get("status") != "active" or not result.get("leaseToken"):
                    raise LicenseError("授权状态或 lease 无效", error_code="LICENSE_INVALID_STATE")
                self.save_license(license_key, result)
                return result
            except KeyDeskError as exc:
                last_error = exc
                self._clear_valid_state()
                if not exc.retryable or attempt >= self.config.max_retries:
                    raise
                time.sleep(0.25 * (2**attempt))
        assert last_error is not None
        raise last_error

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
        raise KeyDeskConfigError("v2 禁止客户端隐式解绑，请在后台执行显式解绑或换绑")

    def cloud_variables(self, as_dict: bool = True) -> dict[str, str] | list[dict[str, Any]]:
        raise KeyDeskConfigError("v2 SDK 不再暴露未受 lease 保护的旧云变量接口")


KeyDesk = KeyDeskApp


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyDesk Python SDK v2")
    parser.add_argument("--config", default="keydesk.json", help="仅包含 baseUrl/softwareId/version 的配置文件")
    parser.add_argument("--auth-id", default="", help="卡密；省略时读取受保护的本地状态")
    parser.add_argument("command", choices=["validate", "require-license"], nargs="?", default="validate")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = KeyDeskApp.from_file(args.config).require_license(args.auth_id or None)
        print_json({key: value for key, value in result.items() if key != "leaseToken"})
    except KeyDeskError as exc:
        suffix = f" requestId={exc.request_id}" if exc.request_id else ""
        print(f"error [{exc.error_code}]: {exc}{suffix}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
