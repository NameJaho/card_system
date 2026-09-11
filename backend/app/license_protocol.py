from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .config import Settings, get_settings


BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def b64url_decode(value: str, expected_length: int | None = None) -> bytes:
    if not value or not BASE64URL_RE.fullmatch(value):
        raise ValueError("invalid base64url")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if b64url_encode(raw) != value:
        raise ValueError("non-canonical base64url")
    if expected_length is not None and len(raw) != expected_length:
        raise ValueError("invalid decoded length")
    return raw


def normalize_license_key(value: str) -> str:
    return str(value or "").strip().upper()


def license_lookup_value(value: str, pepper: str | None = None) -> str:
    secret = (pepper if pepper is not None else get_settings().license_pepper).encode("utf-8")
    return hmac.new(secret, normalize_license_key(value).encode("utf-8"), hashlib.sha256).hexdigest()


def license_last4(value: str) -> str:
    return normalize_license_key(value)[-4:]


def license_message_hash(value: str) -> str:
    return hashlib.sha256(normalize_license_key(value).encode("utf-8")).hexdigest()


def device_thumbprint(public_key_b64: str) -> str:
    return hashlib.sha256(b64url_decode(public_key_b64, 32)).hexdigest()


def canonical_device_message(
    software_id: str,
    license_key: str,
    installation_id: str,
    client_version: str,
    device_public_key: str,
    request_nonce: str,
    request_time: str,
) -> bytes:
    fields = (
        "KEYDESK-LICENSE-V2",
        software_id,
        license_message_hash(license_key),
        installation_id,
        client_version,
        device_public_key,
        request_nonce,
        request_time,
    )
    if any("\n" in field or "\r" in field for field in fields):
        raise ValueError("canonical field contains newline")
    return "\n".join(fields).encode("utf-8")


def verify_device_signature(public_key_b64: str, signature_b64: str, message: bytes) -> str:
    public_raw = b64url_decode(public_key_b64, 32)
    signature = b64url_decode(signature_b64, 64)
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, message)
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("invalid device proof") from exc
    return hashlib.sha256(public_raw).hexdigest()


@dataclass(frozen=True)
class SigningMaterial:
    kid: str
    private_key: Ed25519PrivateKey
    public_key_b64: str


def _load_private_key(settings: Settings) -> Ed25519PrivateKey:
    if settings.license_signing_key_file:
        raw = Path(settings.license_signing_key_file).read_bytes()
        key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError("CARD_LICENSE_SIGNING_KEY_FILE 不是 Ed25519 私钥")
        return key
    if settings.environment in {"production", "prod"}:
        raise RuntimeError("生产环境缺少 Ed25519 授权签名私钥")
    seed = hashlib.sha256(b"keydesk-development-only-ed25519-signing-key").digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


@lru_cache
def signing_material() -> SigningMaterial:
    settings = get_settings()
    private_key = _load_private_key(settings)
    public_raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return SigningMaterial(settings.license_signing_key_id, private_key, b64url_encode(public_raw))


def trusted_public_keys() -> dict[str, str]:
    settings = get_settings()
    try:
        previous = json.loads(settings.license_previous_public_keys or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("CARD_LICENSE_PREVIOUS_PUBLIC_KEYS 必须是 JSON 对象") from exc
    if not isinstance(previous, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in previous.items()):
        raise RuntimeError("CARD_LICENSE_PREVIOUS_PUBLIC_KEYS 必须是 kid 到公钥的 JSON 对象")
    material = signing_material()
    result = dict(previous)
    result[material.kid] = material.public_key_b64
    for key in result.values():
        b64url_decode(key, 32)
    return result


def sign_jws(claims: dict[str, Any]) -> str:
    material = signing_material()
    header = {"alg": "EdDSA", "typ": "JWT", "kid": material.kid}
    encoded_header = b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    encoded_claims = b64url_encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = b64url_encode(material.private_key.sign(signing_input))
    return f"{encoded_header}.{encoded_claims}.{signature}"


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex
