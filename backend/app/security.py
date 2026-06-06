from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import AdminUser

ROLE_DEVELOPER = "developer"
ROLE_ADMIN = "admin"
ROLE_USER = "user"

ROLE_LABELS = {
    ROLE_DEVELOPER: "超级管理员",
    ROLE_ADMIN: "管理员",
    ROLE_USER: "普通用户",
}

ROLE_ALIASES = {
    "developer": ROLE_DEVELOPER,
    "super": ROLE_DEVELOPER,
    "super_admin": ROLE_DEVELOPER,
    "superadmin": ROLE_DEVELOPER,
    "root": ROLE_DEVELOPER,
    "超级管理员": ROLE_DEVELOPER,
    "开发者": ROLE_DEVELOPER,
    "admin": ROLE_ADMIN,
    "manager": ROLE_ADMIN,
    "管理员": ROLE_ADMIN,
    "user": ROLE_USER,
    "normal": ROLE_USER,
    "普通用户": ROLE_USER,
}

DEVELOPER_PERMISSIONS = [
    "softView",
    "softCreate",
    "softEdit",
    "softDelete",
    "authCreate",
    "authDelete",
    "authExport",
    "authUnbind",
    "userView",
    "cloudVarView",
    "cloudVarAdd",
    "cloudVarDelete",
    "blackWhiteView",
    "blackWhiteAdd",
    "blackWhiteDelete",
    "accountManage",
    "eventView",
    "messageManage",
]

ROLE_PERMISSIONS = {
    ROLE_DEVELOPER: DEVELOPER_PERMISSIONS,
    ROLE_ADMIN: ["softView", "softCreate", "softEdit", "softDelete", "authCreate", "accountManage"],
    ROLE_USER: ["softView", "authCreate"],
}


def normalize_role(value: str | None) -> str:
    return ROLE_ALIASES.get(str(value or "").strip().lower(), ROLE_USER)


def role_label(value: str | None) -> str:
    return ROLE_LABELS.get(normalize_role(value), "普通用户")


def role_permissions(role: str | None) -> list[str]:
    return list(ROLE_PERMISSIONS.get(normalize_role(role), ROLE_PERMISSIONS[ROLE_USER]))


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, salt, digest = password_hash.split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    return hmac.compare_digest(hash_password(password, salt), password_hash)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_token(subject: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    exp = datetime.utcnow() + timedelta(minutes=expires_minutes or settings.token_expire_minutes)
    payload = {"sub": subject, "exp": int(exp.timestamp())}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def decode_token(raw: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        body, sig = raw.split(".", 1)
        expected = _b64(hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        payload = json.loads(_unb64(body))
        if int(payload["exp"]) < int(datetime.utcnow().timestamp()):
            raise ValueError("expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 失效了") from exc


def current_user(token: str | None = Header(default=None), db: Session = Depends(get_db)) -> AdminUser:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少 token")
    payload = decode_token(token)
    user = db.query(AdminUser).filter(AdminUser.user == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


def permission_list(user: AdminUser) -> list[str]:
    return role_permissions(getattr(user, "role", ROLE_USER))


def software_scope(user: AdminUser) -> list[str]:
    try:
        return json.loads(user.software_ids or "[]")
    except json.JSONDecodeError:
        return []


def has_permission(user: AdminUser, code: str) -> bool:
    if normalize_role(getattr(user, "role", ROLE_USER)) == ROLE_DEVELOPER:
        return True
    return code in permission_list(user)


def require_permission(code: str):
    def dep(user: AdminUser = Depends(current_user)) -> AdminUser:
        if not has_permission(user, code):
            raise HTTPException(status_code=403, detail="您没有访问权限")
        return user

    return dep


def owner_id_for(user: AdminUser) -> int:
    return user.parent_id or user.id


def new_token_value(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]
