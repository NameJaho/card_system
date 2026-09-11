from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import smtplib
import zipfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from packaging.version import InvalidVersion, Version
from sqlalchemy import and_, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, get_db
from .config import get_settings, validate_production_settings
from .models import (
    AdminUser,
    AuthCard,
    BlackWhiteItem,
    CloudVariable,
    Customer,
    EventLog,
    LicenseAuditEvent,
    LicenseRequestNonce,
    LicenseSigningKey,
    Message,
    PasswordResetToken,
    SoftwareInstance,
)
from .license_protocol import (
    b64url_decode,
    canonical_device_message,
    license_last4,
    license_lookup_value,
    new_request_id,
    sign_jws,
    signing_material,
    trusted_public_keys,
    verify_device_signature,
)
from .security import (
    create_token,
    current_user,
    hash_password,
    has_permission,
    new_token_value,
    normalize_role,
    owner_id_for,
    permission_list,
    require_permission,
    role_permissions,
    ROLE_ADMIN,
    ROLE_DEVELOPER,
    ROLE_USER,
    software_scope,
    verify_password,
)
from .seed import seed_database
from .serializers import (
    auth_dict,
    black_white_dict,
    cloud_var_dict,
    customer_dict,
    event_dict,
    license_audit_dict,
    message_dict,
    software_dict,
    user_dict,
)
from .utils import api_error, fail, ok, paged, parse_time_range, random_code, rate_limiter


settings = get_settings()
app = FastAPI(title="Card System API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "token"],
)


@app.on_event("startup")
def startup() -> None:
    validate_production_settings(get_settings())
    material = signing_material()
    verification_keys = trusted_public_keys()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(LicenseSigningKey).filter(LicenseSigningKey.kid.notin_(verification_keys)).update(
            {"status": "retired"}, synchronize_session=False
        )
        for kid, public_key in verification_keys.items():
            row = db.query(LicenseSigningKey).filter(LicenseSigningKey.kid == kid).first()
            if not row:
                row = LicenseSigningKey(kid=kid, public_key=public_key, status="active" if kid == material.kid else "verifying")
                db.add(row)
            else:
                row.public_key = public_key
                row.status = "active" if kid == material.kid else "verifying"
        seed_database(db)


class Body(dict):
    pass


class AnyBody(BaseModel):
    model_config = {"extra": "allow"}


class LicenseValidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    softwareId: str = Field(min_length=1, max_length=80)
    licenseKey: str = Field(min_length=1, max_length=120)
    installationId: str = Field(min_length=1, max_length=255)
    clientVersion: str = Field(min_length=1, max_length=80)

    @field_validator("softwareId", "licenseKey", "installationId", "clientVersion")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class LicenseValidateV2Body(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocolVersion: int
    softwareId: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    licenseKey: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    installationId: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    clientVersion: str = Field(min_length=1, max_length=80, pattern=r"^[0-9A-Za-z.+_-]+$")
    devicePublicKey: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")
    requestNonce: str = Field(min_length=32, max_length=86, pattern=r"^[A-Za-z0-9_-]+$")
    requestTime: str = Field(min_length=20, max_length=32, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
    deviceSignature: str = Field(min_length=86, max_length=86, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("protocolVersion")
    @classmethod
    def require_v2(cls, value: int) -> int:
        if value != 2:
            raise ValueError("protocolVersion must be 2")
        return value


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/client/v1/"):
        return api_error("INVALID_REQUEST", "请求字段缺失或格式错误", 422)
    if request.url.path.startswith("/api/client/v2/"):
        return api_error("INVALID_REQUEST", "请求字段缺失或格式错误", 422, request_id=new_request_id())
    return await request_validation_exception_handler(request, exc)


def body_dict(body: AnyBody | None) -> dict[str, Any]:
    return body.model_dump() if body else {}


def is_developer(user: AdminUser) -> bool:
    return normalize_role(getattr(user, "role", ROLE_USER)) == ROLE_DEVELOPER


def ensure_developer(user: AdminUser) -> None:
    if not is_developer(user):
        raise HTTPException(status_code=403, detail="您没有访问权限")


def manageable_user_query(db: Session, user: AdminUser):
    role = normalize_role(user.role)
    if role == ROLE_DEVELOPER:
        return db.query(AdminUser).filter(AdminUser.id != user.id)
    if role == ROLE_ADMIN:
        return db.query(AdminUser).filter(AdminUser.parent_id == user.id)
    raise HTTPException(status_code=403, detail="您没有访问权限")


def assert_assignable_role(actor: AdminUser, role: str) -> None:
    actor_role = normalize_role(actor.role)
    if actor_role == ROLE_DEVELOPER:
        return
    if actor_role == ROLE_ADMIN and role == ROLE_USER:
        return
    raise HTTPException(status_code=403, detail="您没有访问权限")


def parent_id_for_role(actor: AdminUser, role: str, current_parent_id: int | None = None) -> int | None:
    if role in (ROLE_DEVELOPER, ROLE_ADMIN):
        return None
    return current_parent_id or actor.id


def normalize_software_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def request_ip(request: Request | None) -> str | None:
    if not request:
        return None
    forwarded = str(request.headers.get("x-real-ip") or "").strip()
    if forwarded:
        return forwarded[:80]
    return request.client.host[:80] if request.client else None


def add_event(
    db: Session,
    owner_id: int | None,
    type_: str,
    keyword: str,
    message: str,
    request: Request | None = None,
    **kwargs,
) -> None:
    db.add(
        EventLog(
            owner_id=owner_id,
            type=type_,
            keyword=keyword,
            message=message,
            ip=request_ip(request),
            result=kwargs.pop("result", "success"),
            software_id=kwargs.pop("software_id", None),
            auth_id=kwargs.pop("auth_id", None),
            customer_id=kwargs.pop("customer_id", None),
            macid=kwargs.pop("macid", None),
        )
    )


def visible_software_query(db: Session, user: AdminUser):
    q = db.query(SoftwareInstance)
    role = normalize_role(user.role)
    if role == ROLE_DEVELOPER:
        return q
    owner_id = owner_id_for(user)
    if role == ROLE_ADMIN:
        return q.filter(SoftwareInstance.owner_id == owner_id)
    scope = software_scope(user)
    if "*" in scope:
        return q.filter(SoftwareInstance.owner_id == owner_id)
    return q.filter(SoftwareInstance.owner_id == owner_id, SoftwareInstance.software_id.in_(scope or [""]))


def tenant_query(db: Session, model, user: AdminUser):
    return db.query(model).filter(model.owner_id == owner_id_for(user))


def visible_software_ids(db: Session, user: AdminUser) -> list[str]:
    return [row.software_id for row in visible_software_query(db, user).all()]


def visible_auth_query(db: Session, user: AdminUser):
    ids = visible_software_ids(db, user)
    q = db.query(AuthCard).filter(AuthCard.software_id.in_(ids or [""]))
    if normalize_role(user.role) == ROLE_USER:
        q = q.filter(AuthCard.creator_id == user.id)
    return q


def auth_reference_filter(value: Any):
    raw = text_value(value)
    if raw.startswith("CARD_"):
        return AuthCard.auth_id == raw
    return AuthCard.license_lookup == license_lookup_value(raw)


def visible_auth_card(db: Session, user: AdminUser, value: Any) -> AuthCard | None:
    raw = text_value(value)
    if not raw:
        return None
    return visible_auth_query(db, user).filter(auth_reference_filter(raw)).first()


def get_software_or_404(db: Session, user: AdminUser, software_id: str) -> SoftwareInstance:
    row = visible_software_query(db, user).filter(SoftwareInstance.software_id == software_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="实例不存在")
    return row


def software_owner_by_id(db: Session, software_id: str) -> int | None:
    row = db.query(SoftwareInstance).filter(SoftwareInstance.software_id == software_id).first()
    return row.owner_id if row else None


def client_software_or_fail(db: Session, data: dict[str, Any]) -> tuple[SoftwareInstance | None, str]:
    soft = db.query(SoftwareInstance).filter(SoftwareInstance.software_id == data.get("softwareId")).first()
    if not soft:
        return None, "实例不存在"
    incoming_key = str(data.get("instanceKey") or data.get("privateKey") or "").strip()
    stored_key = str(soft.instance_key or "").strip()
    if not incoming_key or not stored_key or not hmac.compare_digest(incoming_key, stored_key):
        return None, "实例密钥错误"
    return soft, ""


AUTH_STATUS_ALIASES = {
    True: "active",
    False: "unused",
    1: "active",
    2: "unused",
    "1": "active",
    "2": "unused",
    "true": "active",
    "false": "unused",
    "active": "active",
    "unused": "unused",
    "expired": "expired",
    "disabled": "disabled",
    "revoked": "revoked",
}


def text_value(value: Any) -> str:
    return str(value or "").strip()


def normalize_auth_status(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return AUTH_STATUS_ALIASES.get(value.strip().lower())
    return AUTH_STATUS_ALIASES.get(value)


def apply_auth_filters(query, data: dict[str, Any]):
    software_id = text_value(data.get("softwareId"))
    auth_id = text_value(data.get("authId"))
    macid = text_value(data.get("macid"))
    keyword = text_value(data.get("keyword"))
    status = normalize_auth_status(data.get("status"))

    if software_id:
        query = query.filter(AuthCard.software_id == software_id)
    if auth_id:
        if auth_id.startswith("CARD_"):
            query = query.filter(AuthCard.auth_id.contains(auth_id))
        elif len(auth_id) >= 8:
            query = query.filter(or_(AuthCard.license_lookup == license_lookup_value(auth_id), AuthCard.license_last4.contains(auth_id[-4:].upper())))
        else:
            query = query.filter(AuthCard.license_last4.contains(auth_id.upper()))
    if macid:
        query = query.filter(AuthCard.macid.contains(macid))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                AuthCard.auth_id.like(like),
                AuthCard.license_last4.like(like),
                AuthCard.software_id.like(like),
                AuthCard.macid.like(like),
                AuthCard.remark.like(like),
                AuthCard.assigned_sub_user.like(like),
            )
        )
    if status:
        query = query.filter(AuthCard.status == status)
    return query


def valid_sha256(value: Any) -> bool:
    raw = text_value(value)
    return not raw or bool(re.fullmatch(r"[0-9a-fA-F]{64}", raw))


@app.get("/health")
def health(db: Session = Depends(get_db)):
    settings = get_settings()
    schema_version = settings.schema_version
    try:
        schema_version = str(db.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
    except Exception:
        db.rollback()
    return ok(
        {
            "status": "ok",
            "appVersion": settings.app_version,
            "gitSha": settings.git_sha,
            "schemaVersion": schema_version,
            "protocolVersions": [1, 2],
            "activeSigningKid": signing_material().kid,
            "sdkVersion": "2.0.0",
        }
    )


@app.post("/api/adm/login")
def login(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    ip = request_ip(request) or "unknown"
    if not rate_limiter.allow(f"adm-login:{ip}", 30, 60):
        return fail("请求过于频繁", status_code=429, error_code="RATE_LIMITED", retryable=True)
    user = db.query(AdminUser).filter(AdminUser.user == data.get("user", "")).first()
    if not user or not verify_password(str(data.get("password", "")), user.password_hash):
        add_event(db, None, "security", "login", "后台登录失败", request, result="failed")
        db.commit()
        return fail("账号或密码错误")
    if data.get("fingerId"):
        user.finger_id = str(data["fingerId"])
    user.last_login = datetime.utcnow()
    token = create_token(user.user, token_version=user.token_version or 0)
    add_event(db, owner_id_for(user), "login", user.user, "后台登录成功", request, result="success")
    db.commit()
    res = user_dict(user, include_private=is_developer(user))
    res.update({"token": token, "isSubUser": bool(user.parent_id), "permissions": {"permissionTypes": permission_list(user), "softwareIds": software_scope(user)}})
    return ok(res)


@app.post("/api/adm/fingerLogin")
def finger_login(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    ip = request_ip(request) or "unknown"
    if not rate_limiter.allow(f"finger-login:{ip}", 30, 60):
        return fail("请求过于频繁", status_code=429, error_code="RATE_LIMITED", retryable=True)
    user = db.query(AdminUser).filter(AdminUser.user == data.get("user", ""), AdminUser.finger_id == data.get("fingerId", "")).first()
    if not user:
        add_event(db, None, "security", "fingerLogin", "免密码登录失败", request, result="failed")
        db.commit()
        return fail("免密码登录失败")
    token = create_token(user.user, token_version=user.token_version or 0)
    add_event(db, owner_id_for(user), "login", user.user, "免密码登录成功", request)
    db.commit()
    res = user_dict(user, include_private=is_developer(user))
    res.update({"token": token, "isSubUser": bool(user.parent_id), "permissions": {"permissionTypes": permission_list(user), "softwareIds": software_scope(user)}})
    return ok(res)


@app.post("/api/adm/register")
def register(body: AnyBody, db: Session = Depends(get_db)):
    return fail("后台注册已关闭，请联系超级管理员创建账号")


@app.post("/api/adm/forgotPassword")
def forgot_password(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    settings = get_settings()
    email = str(data.get("email") or "").strip().lower()
    ip = request_ip(request) or "unknown"
    if not rate_limiter.allow(f"reset-ip:{ip}", 10, 3600) or not rate_limiter.allow(f"reset-email:{email}", 5, 3600):
        return fail("请求过于频繁", status_code=429, error_code="RATE_LIMITED", retryable=True)
    if not settings.allow_dev_reset_link and not settings.smtp_host:
        return fail("密码重置服务暂不可用", status_code=503, error_code="RESET_UNAVAILABLE", retryable=True)

    generic_message = "如果该邮箱已注册，重置邮件将很快发送"
    user = db.query(AdminUser).filter(AdminUser.email == email).first()
    if not user:
        return ok(None, generic_message)

    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.utcnow()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    reset = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + timedelta(minutes=settings.password_reset_minutes),
        requested_ip=ip,
    )
    db.add(reset)
    db.commit()

    if settings.allow_dev_reset_link:
        return ok({"resetToken": raw_token}, generic_message)

    reset_url = f"{settings.public_base_url}/#/reset-password?token={raw_token}"
    message = EmailMessage()
    message["Subject"] = "KeyDesk 密码重置"
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = user.email
    message.set_content(f"请在 {settings.password_reset_minutes} 分钟内打开以下链接重置密码：\n\n{reset_url}\n")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except Exception:
        reset.used_at = datetime.utcnow()
        add_event(db, owner_id_for(user), "security", "passwordResetEmail", "密码重置邮件发送失败", request, result="failed")
        db.commit()
        return ok(None, generic_message)
    return ok(None, generic_message)


@app.post("/api/adm/resetUserPassword")
def reset_user_password(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    raw_token = str(data.get("token") or "").strip()
    password = str(data.get("password") or "")
    ip = request_ip(request) or "unknown"
    if not rate_limiter.allow(f"reset-consume:{ip}", 20, 3600):
        return fail("请求过于频繁", status_code=429, error_code="RATE_LIMITED", retryable=True)
    if not raw_token or len(password) < 8:
        return fail("重置令牌无效或新密码少于 8 位", error_code="RESET_TOKEN_INVALID")
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.utcnow()
    reset = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()
    if not reset:
        return fail("重置令牌无效或已过期", error_code="RESET_TOKEN_INVALID")
    consumed = db.query(PasswordResetToken).filter(
        PasswordResetToken.id == reset.id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > now,
    ).update({"used_at": now}, synchronize_session=False)
    if consumed != 1:
        db.rollback()
        return fail("重置令牌无效或已过期", error_code="RESET_TOKEN_INVALID")
    user = db.query(AdminUser).filter(AdminUser.id == reset.user_id).first()
    if not user:
        db.rollback()
        return fail("重置令牌无效或已过期", error_code="RESET_TOKEN_INVALID")
    user.password_hash = hash_password(password)
    user.token_version = (user.token_version or 0) + 1
    add_event(db, owner_id_for(user), "security", "passwordReset", "密码重置成功", request)
    db.commit()
    return ok()


@app.post("/api/adm/rePasswordInfo")
def re_password_info(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    raw_token = str(body_dict(body).get("token") or "").strip()
    ip = request_ip(request) or "unknown"
    if not rate_limiter.allow(f"reset-info:{ip}", 30, 3600):
        return fail("请求过于频繁", status_code=429, error_code="RATE_LIMITED", retryable=True)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest() if raw_token else ""
    row = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > datetime.utcnow(),
    ).first()
    if not row:
        return fail("重置令牌无效或已过期", error_code="RESET_TOKEN_INVALID")
    return ok({"valid": True})


@app.post("/api/adm/user")
def adm_user(user: AdminUser = Depends(current_user)):
    return ok(user_dict(user, include_private=is_developer(user)))


@app.post("/api/adm/updateUserInfo")
def update_user_info(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    data = body_dict(body)
    if any(field in data for field in ("accountToken", "openId")) and not is_developer(user):
        raise HTTPException(status_code=403, detail="您没有访问权限")
    for field, attr in [("email", "email"), ("nick", "nick"), ("qq", "qq"), ("accountToken", "account_token"), ("openId", "open_id")]:
        if field in data and data[field] is not None:
            setattr(user, attr, str(data[field]))
    if data.get("password"):
        user.password_hash = hash_password(data["password"])
        user.token_version = (user.token_version or 0) + 1
    db.commit()
    return ok(user_dict(user, include_private=is_developer(user)))


@app.post("/api/adm/clearFingerId")
def clear_finger(db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    user.finger_id = None
    db.commit()
    return ok()


@app.post("/api/adm/user-config")
def user_config(user: AdminUser = Depends(current_user)):
    settings = get_settings()
    return ok(
        {
            "gitcodeProjectUrl": getattr(user, "gitcode_project_url", None),
            "gitcodeToken": None,
            "gitcodeName": None,
            "gitcodeRepo": None,
            "publicBaseUrl": settings.public_base_url,
            "appVersion": settings.app_version,
            "gitSha": settings.git_sha,
            "schemaVersion": settings.schema_version,
            "protocolVersions": [1, 2],
            "activeSigningKid": signing_material().kid,
            "sdkVersion": "2.0.0",
        }
    )


@app.post("/api/adm/bindGitCode")
def bind_gitcode(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("softEdit"))):
    data = body_dict(body)
    project_url = str(data.get("projectUrl") or "")
    token = str(data.get("token") or "")
    if "gitcode.com" not in project_url or "/" not in project_url:
        return fail("请输入正确的项目地址")
    rows = db.query(SoftwareInstance).filter(SoftwareInstance.owner_id == owner_id_for(user)).all()
    parts = project_url.rstrip("/").split("/")
    for row in rows:
        row.gitcode_project_url = project_url
        row.gitcode_token = token
        row.gitcode_name = parts[-2] if len(parts) >= 2 else None
        row.gitcode_repo = parts[-1] if parts else None
    db.commit()
    return ok()


@app.post("/api/adm/softwareList")
def software_list(body: AnyBody, user: AdminUser = Depends(require_permission("softView")), db: Session = Depends(get_db)):
    data = body_dict(body)
    q = visible_software_query(db, user).order_by(SoftwareInstance.created_at.desc())
    if data.get("softwareName"):
        q = q.filter(SoftwareInstance.name.contains(data["softwareName"]))
    if data.get("softwareId"):
        q = q.filter(SoftwareInstance.software_id.contains(data["softwareId"]))
    return ok(paged(q, data.get("page"), lambda row: software_dict(row, include_secret=True)))


@app.post("/api/adm/softwareSelect")
def software_select(user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    rows = visible_software_query(db, user).order_by(SoftwareInstance.created_at.desc()).all()
    return ok([software_dict(row, include_secret=True) for row in rows])


@app.post("/api/adm/clientPackage")
def client_package(body: AnyBody, user: AdminUser = Depends(require_permission("softView")), db: Session = Depends(get_db)):
    software = get_software_or_404(db, user, text_value(body_dict(body).get("softwareId")))
    candidates = [
        Path(__file__).resolve().parents[2] / "clients" / "python" / "keydesk_client.py",
        Path("/app/client_sdk/keydesk.py"),
    ]
    sdk_path = next((path for path in candidates if path.exists()), None)
    if not sdk_path:
        return fail("SDK 文件未随服务部署", status_code=503, error_code="SDK_PACKAGE_UNAVAILABLE", retryable=True)
    config = {
        "baseUrl": get_settings().public_base_url,
        "softwareId": software.software_id,
        "version": software.version,
    }
    sdk_source = sdk_path.read_text(encoding="utf-8")
    base_placeholder = 'BUILTIN_PRODUCTION_BASE_URL = ""'
    keys_placeholder = "BUILTIN_TRUSTED_LICENSE_KEYS: dict[str, str] = {}"
    if base_placeholder not in sdk_source or keys_placeholder not in sdk_source:
        return fail("SDK 模板缺少生产信任根占位符", status_code=503, error_code="SDK_PACKAGE_INVALID")
    sdk_source = sdk_source.replace(
        base_placeholder,
        f"BUILTIN_PRODUCTION_BASE_URL = {json.dumps(get_settings().public_base_url)}",
        1,
    )
    sdk_source = sdk_source.replace(
        keys_placeholder,
        f"BUILTIN_TRUSTED_LICENSE_KEYS: dict[str, str] = {json.dumps(trusted_public_keys(), sort_keys=True)}",
        1,
    )
    example = (
        "from keydesk import KeyDesk, LicenseError\n\n"
        "license = KeyDesk.from_file('keydesk.json')\n"
        "try:\n"
        "    license.require_license(prompt=lambda: input('请输入卡密：').strip())\n"
        "except LicenseError as exc:\n"
        "    raise SystemExit(f'授权失败 [{exc.error_code}]: {exc}')\n"
    )
    smoke = (
        "import os\n"
        "from keydesk import KeyDesk\n\n"
        "key = os.environ.get('KEYDESK_TEST_LICENSE') or input('测试卡密：').strip()\n"
        "result = KeyDesk.from_file('keydesk.json').require_license(key)\n"
        "print('OK', result['status'], result.get('serverTime'))\n"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("keydesk.py", sdk_source)
        archive.writestr("keydesk.json", json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        archive.writestr("example.py", example)
        archive.writestr("smoke_test.py", smoke)
        archive.writestr(
            "README.txt",
            "先运行 pip install cryptography，再运行 python example.py。v2 必须在线验证签名 lease；不要修改内置服务地址、公钥或关闭 TLS 校验。\n",
        )
    output.seek(0)
    filename = f"keydesk-{software.software_id}-python-v2.zip"
    return StreamingResponse(
        output,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/adm/createSoftware")
def create_software(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("softCreate"))):
    data = body_dict(body)
    if not data.get("name") or not data.get("version"):
        return fail("请输入信息")
    if "|" in data["name"]:
        return fail("请不要使用关键字符 |")
    if not valid_sha256(data.get("sha256")):
        return fail("SHA-256 必须是 64 位十六进制字符串")
    try:
        minimum_protocol = int(data.get("minimumProtocolVersion") or 1)
        lease_ttl = int(data.get("leaseTtlSeconds") or get_settings().license_lease_ttl_seconds)
        next_check = int(data.get("nextCheckAfterSeconds") or get_settings().license_next_check_seconds)
    except (TypeError, ValueError):
        return fail("协议策略必须是整数")
    if minimum_protocol not in {1, 2} or not 30 <= lease_ttl <= 900 or not 10 <= next_check <= lease_ttl:
        return fail("协议策略超出允许范围")
    row = SoftwareInstance(
        owner_id=owner_id_for(user),
        name=data["name"],
        version=data["version"],
        software_id=random_code("SW", 12),
        instance_key=random_code("IK", 32),
        low_version=data.get("lowVersion") or None,
        force=bool(data.get("force")),
        remark=str(data.get("remark") or ""),
        url=data.get("url") or None,
        notice=str(data.get("notice") or ""),
        md5=data.get("md5") or None,
        sha256=data.get("sha256") or None,
        protocol_version="v1",
        strict_client_auth=True,
        minimum_protocol_version=minimum_protocol,
        lease_ttl_seconds=lease_ttl,
        next_check_after_seconds=next_check,
        offline_grace_seconds=0,
        device_proof_required=True,
    )
    db.add(row)
    db.commit()
    return ok(software_dict(row, include_secret=True), "创建成功")


@app.post("/api/adm/updateSoftware")
def update_software(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("softEdit"))):
    data = body_dict(body)
    if not valid_sha256(data.get("sha256")):
        return fail("SHA-256 必须是 64 位十六进制字符串")
    row = get_software_or_404(db, user, data.get("softwareId", ""))
    try:
        minimum_protocol = int(data.get("minimumProtocolVersion", row.minimum_protocol_version))
        lease_ttl = int(data.get("leaseTtlSeconds", row.lease_ttl_seconds))
        next_check = int(data.get("nextCheckAfterSeconds", row.next_check_after_seconds))
    except (TypeError, ValueError):
        return fail("协议策略必须是整数")
    if minimum_protocol not in {1, 2} or not 30 <= lease_ttl <= 900 or not 10 <= next_check <= lease_ttl:
        return fail("协议策略超出允许范围")
    policy_changed = any(
        (
            minimum_protocol != row.minimum_protocol_version,
            lease_ttl != row.lease_ttl_seconds,
            next_check != row.next_check_after_seconds,
        )
    )
    mapping = {
        "name": "name",
        "version": "version",
        "lowVersion": "low_version",
        "force": "force",
        "remark": "remark",
        "url": "url",
        "notice": "notice",
        "md5": "md5",
        "sha256": "sha256",
    }
    for key, attr in mapping.items():
        if key in data:
            setattr(row, attr, data[key])
    row.minimum_protocol_version = minimum_protocol
    row.lease_ttl_seconds = lease_ttl
    row.next_check_after_seconds = next_check
    row.offline_grace_seconds = 0
    row.device_proof_required = True
    if policy_changed:
        row.policy_version = (row.policy_version or 1) + 1
    row.updated_at = datetime.utcnow()
    if not row.instance_key:
        row.instance_key = random_code("IK", 32)
    db.commit()
    return ok(software_dict(row, include_secret=True))


@app.post("/api/adm/rotateInstanceKey")
def rotate_instance_key(body: AnyBody, request: Request, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("softEdit"))):
    row = get_software_or_404(db, user, text_value(body_dict(body).get("softwareId")))
    row.instance_key = random_code("IK", 32)
    row.updated_at = datetime.utcnow()
    add_event(db, row.owner_id, "security", "rotateInstanceKey", "旧协议实例密钥已轮换", request, software_id=row.software_id)
    db.commit()
    return ok(software_dict(row, include_secret=True), "实例密钥已轮换")


@app.post("/api/adm/delSoftware")
def del_software(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("softDelete"))):
    data = body_dict(body)
    row = get_software_or_404(db, user, data.get("softwareId", ""))
    db.query(AuthCard).filter(AuthCard.software_id == row.software_id).delete()
    db.query(CloudVariable).filter(CloudVariable.owner_id == row.owner_id, CloudVariable.software_id == row.software_id).delete()
    db.query(BlackWhiteItem).filter(BlackWhiteItem.owner_id == row.owner_id, BlackWhiteItem.software_id == row.software_id).delete()
    db.query(LicenseRequestNonce).filter(LicenseRequestNonce.software_id == row.software_id).delete()
    db.query(LicenseAuditEvent).filter(LicenseAuditEvent.software_id == row.software_id).delete()
    db.delete(row)
    db.commit()
    return ok()


@app.post("/api/adm/authList")
def auth_list(body: AnyBody, user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    if not any(has_permission(user, code) for code in ("authCreate", "authDelete", "authExport", "authUnbind")):
        raise HTTPException(status_code=403, detail="您没有访问权限")
    data = body_dict(body)
    q = visible_auth_query(db, user).order_by(AuthCard.created_at.desc())
    q = apply_auth_filters(q, data)
    return ok(paged(q, data.get("page"), auth_dict))


@app.post("/api/adm/createAuth")
def create_auth(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authCreate"))):
    data = body_dict(body)
    software = get_software_or_404(db, user, data.get("softwareId", ""))
    try:
        count = int(data.get("createNumber") or 1)
        day = int(data.get("day") or 0)
        hour = int(data.get("hour") or 0)
        minute = int(data.get("minute") or 0)
    except (TypeError, ValueError):
        return fail("数量和有效期必须是数字")
    if count < 1 or count > 100:
        return fail("创建数量必须在 1 到 100 之间")
    if min(day, hour, minute) < 0:
        return fail("有效期不能小于 0")
    bind_count = data.get("bindCount")
    if bind_count in ("", None):
        bind_count = None
    else:
        try:
            bind_count = int(bind_count)
        except (TypeError, ValueError):
            return fail("绑定次数必须是数字")
        if bind_count < 0:
            return fail("绑定次数不能小于 0")
    rows = []
    for _ in range(count):
        raw_license_key = random_code("KM", 20)
        row = AuthCard(
            owner_id=software.owner_id,
            software_id=software.software_id,
            auth_id=random_code("CARD_", 24),
            license_lookup=license_lookup_value(raw_license_key),
            license_last4=license_last4(raw_license_key),
            creator_id=user.id,
            creator_user=user.user,
            creator_role=normalize_role(user.role),
            day=day,
            hour=hour,
            minute=minute,
            bind_count=bind_count,
            remark=data.get("remark") or "",
        )
        db.add(row)
        rows.append((row, raw_license_key))
    db.commit()
    return ok([auth_dict(row, issued_license_key=raw_license_key) for row, raw_license_key in rows], "创建成功")


@app.post("/api/adm/editAuth")
def edit_auth(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authUnbind"))):
    data = body_dict(body)
    row = visible_auth_card(db, user, data.get("cardRef") or data.get("authId"))
    if not row:
        return fail("卡密不存在")
    row.bind_count = data.get("bindCount")
    db.commit()
    return ok(auth_dict(row))


@app.post("/api/adm/commitUnBind")
def commit_unbind(body: AnyBody, request: Request, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authUnbind"))):
    data = body_dict(body)
    row = visible_auth_card(db, user, data.get("cardRef") or data.get("authId"))
    if not row:
        return fail("卡密不存在")
    row.macid = data.get("macid") or None
    if row.macid is None:
        row.bind_used = 0
        row.status = "unused"
    else:
        row.status = "active"
    row.device_public_key = None
    row.device_key_thumbprint = None
    row.protocol_version = 1
    add_event(
        db,
        row.owner_id,
        "security",
        "explicitRebind",
        "管理员显式解绑" if row.macid is None else "管理员显式换绑",
        request,
        software_id=row.software_id,
        auth_id=f"ref:{row.auth_id}:last4:{row.license_last4}",
        macid=row.macid,
    )
    db.commit()
    return ok(auth_dict(row))


@app.post("/api/adm/revokeAuth")
def revoke_auth(body: AnyBody, request: Request, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authUnbind"))):
    data = body_dict(body)
    row = visible_auth_card(db, user, data.get("cardRef") or data.get("authId"))
    if not row:
        return fail("卡密不存在")
    row.status = "revoked"
    row.revoked_at = datetime.utcnow()
    add_event(
        db,
        row.owner_id,
        "security",
        "revokeAuth",
        "卡密已撤销",
        request,
        software_id=row.software_id,
        auth_id=f"ref:{row.auth_id}:last4:{row.license_last4}",
        macid=row.macid,
    )
    db.commit()
    return ok(auth_dict(row), "卡密已撤销")


@app.post("/api/adm/updateAuthRemark")
def update_auth_remark(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authUnbind"))):
    data = body_dict(body)
    row = visible_auth_card(db, user, data.get("cardRef") or data.get("authId"))
    if not row:
        return fail("卡密不存在")
    row.remark = data.get("remark") or ""
    db.commit()
    return ok(auth_dict(row))


@app.post("/api/adm/delAuth")
def del_auth(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authDelete"))):
    data = body_dict(body)
    row = visible_auth_card(db, user, data.get("cardRef") or data.get("authId"))
    if row:
        db.delete(row)
        db.commit()
    return ok()


@app.post("/api/adm/batchDelAuth")
def batch_del_auth(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authDelete"))):
    data = body_dict(body)
    ids = data.get("list") or []
    visible_ids = visible_software_ids(db, user)
    conditions = [auth_reference_filter(value) for value in ids if text_value(value)]
    if conditions:
        db.query(AuthCard).filter(AuthCard.software_id.in_(visible_ids or [""]), or_(*conditions)).delete(synchronize_session=False)
    db.commit()
    return ok()


@app.post("/api/adm/exportTable")
def export_table(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("authExport"))):
    data = body_dict(body)
    q = visible_auth_query(db, user)
    q = apply_auth_filters(q, data)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["cardRef", "licenseLast4", "softwareId", "status", "macid", "endTime", "remark", "creatorUser", "creatorRole"])
    for row in q.order_by(AuthCard.created_at.desc()).all():
        writer.writerow([row.auth_id, row.license_last4, row.software_id, row.status, row.macid or "", row.end_time or "", row.remark, row.creator_user or "", row.creator_role or ""])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=auth_cards.csv"})


@app.post("/api/adm/assignAuthToSubUser")
def assign_auth_to_sub_user(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("accountManage"))):
    data = body_dict(body)
    sub = data.get("subUserName")
    ids = data.get("authIds") or []
    visible_ids = visible_software_ids(db, user)
    conditions = [auth_reference_filter(value) for value in ids if text_value(value)]
    if conditions:
        db.query(AuthCard).filter(AuthCard.software_id.in_(visible_ids or [""]), or_(*conditions)).update({"assigned_sub_user": sub}, synchronize_session=False)
    db.commit()
    return ok({"assigned": len(ids)}, "分配成功")


@app.post("/api/adm/customerList")
def customer_list(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("userView"))):
    data = body_dict(body)
    q = tenant_query(db, Customer, user).order_by(Customer.created_at.desc())
    if data.get("email"):
        q = q.filter(Customer.email.contains(data["email"]))
    if data.get("customerId"):
        q = q.filter(Customer.customer_id.contains(data["customerId"]))
    return ok(paged(q, data.get("page"), customer_dict))


@app.post("/api/adm/delCustomer")
def del_customer(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("userView"))):
    data = body_dict(body)
    row = tenant_query(db, Customer, user).filter(Customer.customer_id == data.get("customerId")).first()
    if row:
        db.delete(row)
        db.commit()
    return ok()


@app.post("/api/adm/cloudVariablesList")
def cloud_variables_list(user: AdminUser = Depends(require_permission("cloudVarView")), db: Session = Depends(get_db)):
    rows = tenant_query(db, CloudVariable, user).all()
    return ok({"variables": json.dumps([cloud_var_dict(row) for row in rows], ensure_ascii=False)})


@app.post("/api/adm/saveCloudVariables")
def save_cloud_variables(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    if not any(has_permission(user, code) for code in ("cloudVarAdd", "cloudVarDelete")):
        raise HTTPException(status_code=403, detail="您没有访问权限")
    data = body_dict(body)
    owner_id = owner_id_for(user)
    variables = data.get("variables") or []
    seen = set()
    for item in variables:
        key = (item.get("softwareId") or "", item.get("key", "").strip().lower())
        if not key[1]:
            continue
        if key in seen:
            return fail(f"变量名重复: {item.get('key')}")
        seen.add(key)
    tenant_query(db, CloudVariable, user).delete()
    for item in variables:
        if item.get("key"):
            db.add(CloudVariable(owner_id=owner_id, key=item["key"], value=item.get("value") or "", status=item.get("status") or "y", software_id=item.get("softwareId") or ""))
    db.commit()
    return ok()


@app.post("/api/adm/blackWhiteList")
def black_white_list(user: AdminUser = Depends(require_permission("blackWhiteView")), db: Session = Depends(get_db)):
    rows = tenant_query(db, BlackWhiteItem, user).all()
    return ok({"list": [black_white_dict(row) for row in rows]})


@app.post("/api/adm/saveBlackWhiteList")
def save_black_white_list(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    if not any(has_permission(user, code) for code in ("blackWhiteAdd", "blackWhiteDelete")):
        raise HTTPException(status_code=403, detail="您没有访问权限")
    data = body_dict(body)
    owner_id = owner_id_for(user)
    items = data.get("list") or []
    seen = set()
    for item in items:
        key = (item.get("softwareId") or "", item.get("type") or "white", str(item.get("value") or "").strip().lower())
        if not key[2]:
            continue
        if key in seen:
            return fail(f"{item.get('type')} 值重复: {item.get('value')}")
        seen.add(key)
    tenant_query(db, BlackWhiteItem, user).delete()
    for item in items:
        if item.get("value"):
            db.add(BlackWhiteItem(owner_id=owner_id, type=item.get("type") or "white", value=item["value"], remark=item.get("remark") or "", software_id=item.get("softwareId") or ""))
    db.commit()
    return ok()


@app.post("/api/adm/message/event")
def message_event(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("eventView"))):
    data = body_dict(body)
    q = tenant_query(db, EventLog, user).order_by(EventLog.created_at.desc())
    if data.get("type"):
        q = q.filter(EventLog.type == data["type"])
    if data.get("keyword"):
        keyword = f"%{data['keyword']}%"
        q = q.filter(or_(EventLog.keyword.like(keyword), EventLog.message.like(keyword), EventLog.auth_id.like(keyword), EventLog.macid.like(keyword)))
    start, end = parse_time_range(data.get("time"))
    if start:
        q = q.filter(EventLog.created_at >= start)
    if end:
        q = q.filter(EventLog.created_at <= end)
    return ok(paged(q, data.get("page"), event_dict))


@app.post("/api/adm/licenseAuditList")
def license_audit_list(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("eventView"))):
    data = body_dict(body)
    visible_ids = visible_software_ids(db, user)
    q = db.query(LicenseAuditEvent).filter(
        LicenseAuditEvent.owner_id == owner_id_for(user),
        LicenseAuditEvent.software_id.in_(visible_ids or [""]),
    )
    if data.get("softwareId"):
        q = q.filter(LicenseAuditEvent.software_id == text_value(data["softwareId"]))
    if data.get("resultCode"):
        q = q.filter(LicenseAuditEvent.result_code == text_value(data["resultCode"]))
    if data.get("keyword"):
        keyword = f"%{text_value(data['keyword'])}%"
        q = q.filter(
            or_(
                LicenseAuditEvent.request_id.like(keyword),
                LicenseAuditEvent.license_ref.like(keyword),
                LicenseAuditEvent.license_last4.like(keyword),
                LicenseAuditEvent.installation_hash.like(keyword),
                LicenseAuditEvent.device_key_thumbprint.like(keyword),
            )
        )
    start, end = parse_time_range(data.get("time"))
    if start:
        q = q.filter(LicenseAuditEvent.created_at >= start)
    if end:
        q = q.filter(LicenseAuditEvent.created_at <= end)
    return ok(paged(q.order_by(LicenseAuditEvent.created_at.desc()), data.get("page"), license_audit_dict))


@app.post("/api/adm/message/list")
def message_list(db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("messageManage"))):
    rows = tenant_query(db, Message, user).order_by(Message.created_at.desc()).limit(50).all()
    return ok([message_dict(row) for row in rows])


@app.post("/api/adm/message/send")
def message_send(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("messageManage"))):
    data = body_dict(body)
    content = str(data.get("content") or "").strip()
    if not content:
        return fail("消息不能为空")
    row = Message(owner_id=owner_id_for(user), content=content)
    db.add(row)
    db.commit()
    return ok(message_dict(row))


@app.post("/api/adm/subUserList")
def sub_user_list(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("accountManage"))):
    data = body_dict(body)
    q = manageable_user_query(db, user).order_by(AdminUser.created_at.desc())
    payload = paged(q, data.get("page"), lambda row: user_dict(row, include_private=False))
    payload["onlineCount"] = q.filter(AdminUser.last_login.isnot(None)).count()
    return ok(payload)


@app.post("/api/adm/createSubUser")
def create_sub_user(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("accountManage"))):
    data = body_dict(body)
    role = normalize_role(data.get("role"))
    assert_assignable_role(user, role)
    username = str(data.get("user") or "").strip()
    if not username or not data.get("password"):
        return fail("账号和密码不能为空")
    if db.query(AdminUser).filter(AdminUser.user == username).first():
        return fail("账号已存在")
    software_ids = normalize_software_ids(data.get("softwareIds"))
    if role == ROLE_USER and not software_ids:
        return fail("普通用户必须选择可访问实例")
    row = AdminUser(
        user=username,
        password_hash=hash_password(data.get("password")),
        email=data.get("email") or "",
        nick=data.get("nick") or username,
        role=role,
        parent_id=parent_id_for_role(user, role),
        account_token=new_token_value("acct_"),
        open_id=new_token_value("open_"),
        permission_types=json.dumps(role_permissions(role), ensure_ascii=False),
        software_ids=json.dumps(software_ids if role == ROLE_USER else ["*"], ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    return ok(user_dict(row, include_private=False))


@app.post("/api/adm/updateSubUser")
def update_sub_user(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("accountManage"))):
    data = body_dict(body)
    row = manageable_user_query(db, user).filter(AdminUser.user == data.get("user")).first()
    if not row:
        return fail("账号不存在")
    role = normalize_role(data.get("role") or row.role)
    assert_assignable_role(user, role)
    row.email = data.get("email") or row.email
    row.nick = data.get("nick") or row.nick
    if data.get("password"):
        row.password_hash = hash_password(data["password"])
        row.token_version = (row.token_version or 0) + 1
    row.role = role
    row.parent_id = parent_id_for_role(user, role, row.parent_id)
    software_ids = normalize_software_ids(data.get("softwareIds"))
    if role == ROLE_USER and not software_ids:
        return fail("普通用户必须选择可访问实例")
    row.permission_types = json.dumps(role_permissions(role), ensure_ascii=False)
    row.software_ids = json.dumps(software_ids if role == ROLE_USER else ["*"], ensure_ascii=False)
    db.commit()
    return ok(user_dict(row, include_private=False))


@app.post("/api/adm/deleteSubUser")
def delete_sub_user(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(require_permission("accountManage"))):
    row = manageable_user_query(db, user).filter(AdminUser.user == body_dict(body).get("user")).first()
    if row:
        db.delete(row)
        db.commit()
    return ok()


@app.post("/api/adm/dataCount")
def data_count(db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    softwares = visible_software_query(db, user).all()
    visible_ids = [soft.software_id for soft in softwares]
    visit_list = []
    activation_query = db.query(AuthCard).filter(AuthCard.status == "active", AuthCard.software_id.in_(visible_ids or [""]))
    month_start = datetime.utcnow() - timedelta(days=30)
    month_query = db.query(EventLog).filter(EventLog.created_at >= month_start, EventLog.software_id.in_(visible_ids or [""]))
    activation_count = activation_query.count()
    month_count = month_query.count()
    for soft in softwares:
        logs = db.query(EventLog).filter(EventLog.software_id == soft.software_id, EventLog.created_at >= datetime.utcnow() - timedelta(days=1)).all()
        buckets: dict[int, int] = {}
        for log in logs:
            buckets[log.created_at.hour] = buckets.get(log.created_at.hour, 0) + 1
        visit_list.append({"name": soft.name, "softwareId": soft.software_id, "visitCount": len(logs), "visitList": [{"hours": k, "value": v} for k, v in sorted(buckets.items())]})
    return ok({"countDaily": [], "visitList": visit_list, "activationCount": activation_count, "monthCount": month_count})


@app.post("/api/adm/softwareVisit")
def software_visit(body: AnyBody, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    software_id = body_dict(body).get("softwareId")
    visible_ids = visible_software_ids(db, user)
    q = db.query(EventLog).filter(EventLog.software_id.in_(visible_ids or [""]))
    if software_id:
        q = q.filter(EventLog.software_id == software_id)
    rows = q.order_by(EventLog.created_at.desc()).limit(300).all()
    return ok([event_dict(row) for row in rows])


def auth_duration(card: AuthCard) -> timedelta | None:
    if card.day == 0 and card.hour == 0 and card.minute == 0:
        return None
    return timedelta(days=card.day, hours=card.hour, minutes=card.minute)


def check_black_white(db: Session, owner_id: int, software_id: str, macid: str | None) -> tuple[bool, str]:
    if not macid:
        return False, "设备码不能为空"
    rows = db.query(BlackWhiteItem).filter(BlackWhiteItem.owner_id == owner_id, BlackWhiteItem.software_id.in_([software_id, ""])).all()
    blacks = {row.value.lower() for row in rows if row.type == "black"}
    whites = {row.value.lower() for row in rows if row.type == "white"}
    value = macid.lower()
    if value in blacks:
        return False, "命中黑名单"
    if whites and value not in whites:
        return False, "不在白名单"
    return True, ""


def credential_hint(value: Any) -> str:
    raw = str(value or "")
    if not raw:
        return "missing"
    digest = license_lookup_value(raw)[:12]
    return f"hmac:{digest}:last4:{raw[-4:]}"


def utc_text(value: datetime | None = None) -> str:
    current = value or datetime.utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_version(value: str) -> Version | None:
    try:
        return Version(value.strip())
    except InvalidVersion:
        return None


def update_result(soft: SoftwareInstance, client_version: str) -> dict[str, Any] | None:
    client = parse_version(client_version)
    latest = parse_version(soft.version or "")
    minimum = parse_version(soft.low_version or "") if soft.low_version else None
    if not client or not latest or (soft.low_version and not minimum):
        return None
    return {
        "updateAvailable": client < latest,
        "updateRequired": bool(minimum and client < minimum),
        "latestVersion": soft.version,
        "minimumVersion": soft.low_version,
        "url": soft.url,
        "notice": soft.notice,
        "sha256": soft.sha256,
    }


LicenseFailure = tuple[str, str, int]


def validate_license_card(
    db: Session,
    soft: SoftwareInstance,
    license_key: str,
    installation_id: str,
    *,
    activate_unused: bool,
) -> tuple[AuthCard | None, LicenseFailure | None]:
    if not license_key:
        return None, ("LICENSE_KEY_REQUIRED", "卡密不能为空", 422)
    if not installation_id:
        return None, ("INSTALLATION_ID_REQUIRED", "设备码不能为空", 422)

    card = (
        db.query(AuthCard)
        .filter(AuthCard.license_lookup == license_lookup_value(license_key), AuthCard.software_id == soft.software_id)
        .with_for_update()
        .first()
    )
    if not card:
        return None, ("LICENSE_NOT_FOUND", "卡密不存在", 404)
    if card.status in {"disabled", "revoked"}:
        return None, ("LICENSE_REVOKED", "卡密已禁用或撤销", 403)
    now = datetime.utcnow()
    if card.status == "expired" or (card.end_time and card.end_time <= now):
        return None, ("LICENSE_EXPIRED", "卡密已过期", 403)

    allowed, reason = check_black_white(db, card.owner_id, card.software_id, installation_id)
    if not allowed:
        return None, ("LICENSE_DEVICE_BLOCKED", reason, 403)

    if card.status == "unused":
        if not activate_unused:
            return None, ("LICENSE_UNUSED", "卡密尚未激活", 409)
        if card.macid and card.macid != installation_id:
            return None, ("LICENSE_DEVICE_MISMATCH", "卡密已绑定其他设备", 409)
        duration = auth_duration(card)
        end_time = card.end_time or (now + duration if duration else None)
        updated = (
            db.query(AuthCard)
            .filter(
                AuthCard.id == card.id,
                AuthCard.status == "unused",
                or_(AuthCard.macid.is_(None), AuthCard.macid == "", AuthCard.macid == installation_id),
            )
            .update(
                {
                    "macid": installation_id,
                    "status": "active",
                    "activated_at": card.activated_at or now,
                    "end_time": end_time,
                    "protocol_version": 1,
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            db.rollback()
            winner = db.query(AuthCard).filter(AuthCard.id == card.id).first()
            if winner and winner.status == "active" and winner.macid == installation_id:
                return winner, None
            return None, ("LICENSE_DEVICE_MISMATCH", "卡密已由其他设备激活", 409)
        db.expire(card)
        db.refresh(card)
        return card, None

    if card.status != "active":
        return None, ("LICENSE_INVALID_STATE", "卡密状态无效", 409)
    if not card.macid or not hmac.compare_digest(card.macid, installation_id):
        return None, ("LICENSE_DEVICE_MISMATCH", "卡密已绑定其他设备", 409)
    return card, None


def audit_license_result(
    db: Session,
    request: Request,
    soft: SoftwareInstance,
    action: str,
    license_key: str,
    installation_id: str,
    *,
    success: bool,
    message: str,
) -> None:
    add_event(
        db,
        soft.owner_id,
        "api",
        action,
        message,
        request,
        result="success" if success else "failed",
        software_id=soft.software_id,
        auth_id=credential_hint(license_key),
        macid=installation_id,
    )


def legacy_license_failure(
    db: Session,
    request: Request,
    soft: SoftwareInstance,
    action: str,
    license_key: str,
    installation_id: str,
    failure: LicenseFailure,
):
    code, message, _ = failure
    audit_license_result(db, request, soft, action, license_key, installation_id, success=False, message=code)
    db.commit()
    return fail(message, error_code=code)


def add_v2_audit(
    db: Session,
    request: Request,
    request_id: str,
    data: dict[str, Any],
    result_code: str,
    *,
    owner_id: int | None = None,
    card: AuthCard | None = None,
    device_thumbprint: str | None = None,
) -> None:
    installation_id = str(data.get("installationId") or "")
    db.add(
        LicenseAuditEvent(
            owner_id=owner_id,
            request_id=request_id,
            software_id=str(data.get("softwareId") or "")[:80],
            license_ref=card.auth_id if card else None,
            license_last4=card.license_last4 if card else license_last4(str(data.get("licenseKey") or "")),
            installation_hash=hashlib.sha256(installation_id.encode("utf-8")).hexdigest() if installation_id else "",
            device_key_thumbprint=device_thumbprint,
            client_version=str(data.get("clientVersion") or "")[:80],
            protocol_version=2,
            result_code=result_code,
            source_ip=request_ip(request),
        )
    )


def consume_v2_nonce(db: Session, data: dict[str, Any], request_id: str, now: datetime) -> bool:
    nonce_raw = b64url_decode(data["requestNonce"])
    if not 24 <= len(nonce_raw) <= 64:
        raise ValueError("nonce length")
    nonce_hash = hashlib.sha256(nonce_raw).hexdigest()
    existing = db.query(LicenseRequestNonce).filter(LicenseRequestNonce.nonce_hash == nonce_hash).first()
    if existing and existing.expires_at > now:
        return False
    if existing:
        db.delete(existing)
        db.flush()
    db.add(
        LicenseRequestNonce(
            nonce_hash=nonce_hash,
            software_id=data["softwareId"],
            request_id=request_id,
            expires_at=now + timedelta(seconds=get_settings().license_nonce_ttl_seconds),
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


def cleanup_license_protocol_records(db: Session, now: datetime) -> None:
    db.query(LicenseRequestNonce).filter(LicenseRequestNonce.expires_at <= now).delete(synchronize_session=False)
    audit_cutoff = now - timedelta(days=get_settings().license_audit_retention_days)
    db.query(LicenseAuditEvent).filter(LicenseAuditEvent.created_at < audit_cutoff).delete(synchronize_session=False)


def validate_v2_card(
    db: Session,
    soft: SoftwareInstance,
    license_key: str,
    installation_id: str,
    device_public_key: str,
    device_thumbprint: str,
    update_required: bool,
) -> tuple[AuthCard | None, LicenseFailure | None]:
    card = (
        db.query(AuthCard)
        .filter(
            AuthCard.license_lookup == license_lookup_value(license_key),
            AuthCard.software_id == soft.software_id,
        )
        .with_for_update()
        .first()
    )
    if not card:
        return None, ("LICENSE_NOT_FOUND", "卡密不存在", 404)
    if card.status in {"disabled", "revoked"}:
        return card, ("LICENSE_REVOKED", "卡密已禁用或撤销", 403)
    now = datetime.utcnow()
    if card.status == "expired" or (card.end_time and card.end_time <= now):
        return card, ("LICENSE_EXPIRED", "卡密已过期", 403)
    allowed, reason = check_black_white(db, card.owner_id, card.software_id, installation_id)
    if not allowed:
        return card, ("LICENSE_DEVICE_BLOCKED", reason, 403)
    if update_required:
        return card, ("CLIENT_UPDATE_REQUIRED", "客户端版本低于最低要求", 426)

    if card.status == "unused":
        if card.macid and not hmac.compare_digest(card.macid, installation_id):
            return card, ("LICENSE_DEVICE_MISMATCH", "卡密已绑定其他设备", 409)
        duration = auth_duration(card)
        end_time = card.end_time or (now + duration if duration else None)
        updated = (
            db.query(AuthCard)
            .filter(
                AuthCard.id == card.id,
                AuthCard.status == "unused",
                or_(AuthCard.macid.is_(None), AuthCard.macid == "", AuthCard.macid == installation_id),
                or_(AuthCard.device_key_thumbprint.is_(None), AuthCard.device_key_thumbprint == ""),
            )
            .update(
                {
                    "macid": installation_id,
                    "device_public_key": device_public_key,
                    "device_key_thumbprint": device_thumbprint,
                    "status": "active",
                    "protocol_version": 2,
                    "activated_at": card.activated_at or now,
                    "end_time": end_time,
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            db.expire_all()
            winner = db.query(AuthCard).filter(AuthCard.id == card.id).first()
            if (
                winner
                and winner.status == "active"
                and winner.macid == installation_id
                and winner.device_key_thumbprint == device_thumbprint
                and winner.device_public_key == device_public_key
            ):
                return winner, None
            return winner, ("LICENSE_DEVICE_MISMATCH", "卡密已由其他设备激活", 409)
        db.expire(card)
        db.refresh(card)
        return card, None

    if card.status != "active":
        return card, ("LICENSE_INVALID_STATE", "卡密状态无效", 409)
    if not card.macid or not hmac.compare_digest(card.macid, installation_id):
        return card, ("LICENSE_DEVICE_MISMATCH", "卡密已绑定其他设备", 409)

    # A v1-bound card may claim its device key once during the explicit migration window.
    if not card.device_key_thumbprint and not card.device_public_key:
        claimed = (
            db.query(AuthCard)
            .filter(
                AuthCard.id == card.id,
                AuthCard.status == "active",
                AuthCard.macid == installation_id,
                AuthCard.device_key_thumbprint.is_(None),
                AuthCard.device_public_key.is_(None),
            )
            .update(
                {
                    "device_public_key": device_public_key,
                    "device_key_thumbprint": device_thumbprint,
                    "protocol_version": 2,
                },
                synchronize_session=False,
            )
        )
        if claimed == 1:
            db.expire(card)
            db.refresh(card)
            return card, None
        db.expire_all()
        card = db.query(AuthCard).filter(AuthCard.id == card.id).first()

    if (
        not card
        or not card.device_key_thumbprint
        or not hmac.compare_digest(card.device_key_thumbprint, device_thumbprint)
        or not card.device_public_key
        or not hmac.compare_digest(card.device_public_key, device_public_key)
    ):
        return card, ("LICENSE_DEVICE_MISMATCH", "卡密已绑定其他设备", 409)
    card.protocol_version = 2
    return card, None


@app.post("/api/client/software/checkUpdate", deprecated=True)
def client_check_update(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    soft, error = client_software_or_fail(db, data)
    if not soft:
        return fail(error, error_code="INSTANCE_KEY_INVALID" if error == "实例密钥错误" else "SOFTWARE_NOT_FOUND")
    if soft.minimum_protocol_version >= 2:
        return api_error("PROTOCOL_UPGRADE_REQUIRED", "该实例要求使用 v2 授权协议", 426, request_id=new_request_id())
    version_data = update_result(soft, str(data.get("version") or ""))
    if not version_data:
        return fail("客户端版本格式错误", error_code="CLIENT_VERSION_INVALID")
    soft.visit += 1
    soft.lasttime = datetime.utcnow()
    add_event(db, soft.owner_id, "api", "checkUpdate", "检查更新", request, software_id=soft.software_id, macid=data.get("macid"))
    db.commit()
    payload = software_dict(soft)
    payload.update(version_data)
    payload["force"] = version_data["updateRequired"]
    return ok(payload)


@app.post("/api/client/auth/activate", deprecated=True)
def client_auth_activate(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    ip = request_ip(request) or "unknown"
    if not rate_limiter.allow(f"license-activate:{ip}", 300, 60):
        return fail("请求过于频繁", status_code=429, error_code="RATE_LIMITED", retryable=True)
    soft, error = client_software_or_fail(db, data)
    if not soft:
        return fail(error, error_code="INSTANCE_KEY_INVALID" if error == "实例密钥错误" else "SOFTWARE_NOT_FOUND")
    if soft.minimum_protocol_version >= 2:
        return api_error("PROTOCOL_UPGRADE_REQUIRED", "该实例要求使用 v2 授权协议", 426, request_id=new_request_id())
    license_key = text_value(data.get("authId"))
    installation_id = text_value(data.get("macid"))
    card, failure = validate_license_card(db, soft, license_key, installation_id, activate_unused=True)
    if failure:
        return legacy_license_failure(db, request, soft, "activate", license_key, installation_id, failure)
    audit_license_result(db, request, soft, "activate", license_key, installation_id, success=True, message="激活成功")
    db.commit()
    assert card is not None
    return ok(auth_dict(card))


@app.post("/api/client/auth/verify", deprecated=True)
def client_auth_verify(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    ip = request_ip(request) or "unknown"
    if not rate_limiter.allow(f"license-verify:{ip}", 300, 60):
        return fail("请求过于频繁", status_code=429, error_code="RATE_LIMITED", retryable=True)
    soft, error = client_software_or_fail(db, data)
    if not soft:
        return fail(error, error_code="INSTANCE_KEY_INVALID" if error == "实例密钥错误" else "SOFTWARE_NOT_FOUND")
    if soft.minimum_protocol_version >= 2:
        return api_error("PROTOCOL_UPGRADE_REQUIRED", "该实例要求使用 v2 授权协议", 426, request_id=new_request_id())
    license_key = text_value(data.get("authId"))
    installation_id = text_value(data.get("macid"))
    card, failure = validate_license_card(db, soft, license_key, installation_id, activate_unused=False)
    if failure:
        return legacy_license_failure(db, request, soft, "verify", license_key, installation_id, failure)
    audit_license_result(db, request, soft, "verify", license_key, installation_id, success=True, message="验证成功")
    db.commit()
    assert card is not None
    return ok(auth_dict(card))


@app.post("/api/client/auth/unbind", deprecated=True)
def client_auth_unbind(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    soft, error = client_software_or_fail(db, data)
    if not soft:
        return fail(error, error_code="INSTANCE_KEY_INVALID" if error == "实例密钥错误" else "SOFTWARE_NOT_FOUND")
    if soft.minimum_protocol_version >= 2:
        return api_error("PROTOCOL_UPGRADE_REQUIRED", "该实例要求使用 v2 授权协议", 426, request_id=new_request_id())
    license_key = text_value(data.get("authId"))
    installation_id = text_value(data.get("macid"))
    card, failure = validate_license_card(db, soft, license_key, installation_id, activate_unused=False)
    if failure:
        return legacy_license_failure(db, request, soft, "unbind", license_key, installation_id, failure)
    assert card is not None
    card.macid = None
    card.status = "unused"
    card.device_public_key = None
    card.device_key_thumbprint = None
    card.protocol_version = 1
    audit_license_result(db, request, soft, "unbind", license_key, installation_id, success=True, message="解绑成功")
    db.commit()
    return ok(auth_dict(card))


@app.post("/api/client/v1/license/validate")
def client_license_validate(body: LicenseValidateBody, request: Request, db: Session = Depends(get_db)):
    data = body.model_dump()
    ip = request_ip(request) or "unknown"
    rate_key = f"license-v1:{ip}:{credential_hint(data['licenseKey'])}"
    if not rate_limiter.allow(rate_key, 300, 60):
        return api_error("RATE_LIMITED", "请求过于频繁", 429, retryable=True)

    soft = db.query(SoftwareInstance).filter(SoftwareInstance.software_id == data["softwareId"]).first()
    if not soft:
        return api_error("SOFTWARE_NOT_FOUND", "实例不存在", 404)
    if soft.minimum_protocol_version >= 2:
        return api_error("PROTOCOL_UPGRADE_REQUIRED", "该实例要求使用 v2 授权协议", 426, request_id=new_request_id())
    version_data = update_result(soft, data["clientVersion"])
    if not version_data:
        return api_error("CLIENT_VERSION_INVALID", "客户端版本格式错误", 422)
    soft.last_protocol_version = 1
    soft.last_client_version = data["clientVersion"]
    soft.last_protocol_at = datetime.utcnow()

    card, failure = validate_license_card(
        db,
        soft,
        data["licenseKey"],
        data["installationId"],
        activate_unused=True,
    )
    if failure:
        code, message, status_code = failure
        audit_license_result(
            db,
            request,
            soft,
            "licenseValidate",
            data["licenseKey"],
            data["installationId"],
            success=False,
            message=code,
        )
        db.commit()
        return api_error(code, message, status_code)

    assert card is not None
    soft.visit += 1
    soft.lasttime = datetime.utcnow()
    audit_license_result(
        db,
        request,
        soft,
        "licenseValidate",
        data["licenseKey"],
        data["installationId"],
        success=True,
        message="验证成功",
    )
    db.commit()
    payload = {
        "status": "active",
        "expiresAt": utc_text(card.end_time) if card.end_time else None,
        "serverTime": utc_text(),
        "nextCheckAfterSeconds": 3600,
        "offlineGraceSeconds": 0,
        "leaseToken": None,
        "requiresOnline": True,
    }
    payload.update(version_data)
    return ok(payload)


@app.post("/api/client/v2/license/validate")
def client_license_validate_v2(body: LicenseValidateV2Body, request: Request, db: Session = Depends(get_db)):
    data = body.model_dump()
    request_id = new_request_id()
    settings = get_settings()
    source_ip = request_ip(request) or "unknown"
    license_rate_key = license_lookup_value(data["licenseKey"])
    installation_rate_key = hashlib.sha256(data["installationId"].encode("utf-8")).hexdigest()
    rate_checks = (
        (f"license-v2-ip:{source_ip}", 60, 60),
        (f"license-v2-software:{data['softwareId']}", 600, 60),
        (f"license-v2-card:{license_rate_key}", 20, 60),
        (f"license-v2-installation:{installation_rate_key}", 20, 60),
    )
    if not all(rate_limiter.allow(key, limit, window) for key, limit, window in rate_checks):
        return api_error("RATE_LIMITED", "请求过于频繁", 429, retryable=True, request_id=request_id)

    now_aware = datetime.now(timezone.utc)
    now = now_aware.replace(tzinfo=None)
    try:
        request_time = datetime.fromisoformat(data["requestTime"].replace("Z", "+00:00"))
    except ValueError:
        return api_error("INVALID_REQUEST", "请求时间格式错误", 422, request_id=request_id)
    if abs((now_aware - request_time).total_seconds()) > settings.license_request_window_seconds:
        add_v2_audit(db, request, request_id, data, "REQUEST_EXPIRED")
        db.commit()
        return api_error("REQUEST_EXPIRED", "请求时间已超出允许窗口", 401, request_id=request_id)

    try:
        canonical = canonical_device_message(
            data["softwareId"],
            data["licenseKey"],
            data["installationId"],
            data["clientVersion"],
            data["devicePublicKey"],
            data["requestNonce"],
            data["requestTime"],
        )
        device_key_thumbprint = verify_device_signature(data["devicePublicKey"], data["deviceSignature"], canonical)
    except ValueError:
        add_v2_audit(db, request, request_id, data, "DEVICE_PROOF_INVALID")
        db.commit()
        return api_error("DEVICE_PROOF_INVALID", "设备证明无效", 401, request_id=request_id)

    cleanup_license_protocol_records(db, now)
    try:
        nonce_accepted = consume_v2_nonce(db, data, request_id, now)
    except ValueError:
        add_v2_audit(db, request, request_id, data, "INVALID_REQUEST", device_thumbprint=device_key_thumbprint)
        db.commit()
        return api_error("INVALID_REQUEST", "nonce 格式错误", 422, request_id=request_id)
    if not nonce_accepted:
        add_v2_audit(db, request, request_id, data, "REQUEST_REPLAYED", device_thumbprint=device_key_thumbprint)
        db.commit()
        return api_error("REQUEST_REPLAYED", "请求 nonce 已使用", 409, request_id=request_id)

    soft = db.query(SoftwareInstance).filter(SoftwareInstance.software_id == data["softwareId"]).first()
    if not soft:
        add_v2_audit(db, request, request_id, data, "SOFTWARE_NOT_FOUND", device_thumbprint=device_key_thumbprint)
        db.commit()
        return api_error("SOFTWARE_NOT_FOUND", "实例不存在", 404, request_id=request_id)

    version_data = update_result(soft, data["clientVersion"])
    if not version_data:
        add_v2_audit(db, request, request_id, data, "INVALID_REQUEST", owner_id=soft.owner_id, device_thumbprint=device_key_thumbprint)
        db.commit()
        return api_error("INVALID_REQUEST", "客户端版本格式错误", 422, request_id=request_id)

    card, failure = validate_v2_card(
        db,
        soft,
        data["licenseKey"],
        data["installationId"],
        data["devicePublicKey"],
        device_key_thumbprint,
        version_data["updateRequired"],
    )
    if failure:
        code, message, status_code = failure
        if not rate_limiter.allow(f"license-v2-failure:{license_rate_key}", 10, 3600):
            code, message, status_code = "RATE_LIMITED", "失败请求过于频繁", 429
        add_v2_audit(
            db,
            request,
            request_id,
            data,
            code,
            owner_id=soft.owner_id,
            card=card,
            device_thumbprint=device_key_thumbprint,
        )
        db.commit()
        return api_error(code, message, status_code, retryable=code == "RATE_LIMITED", request_id=request_id)

    assert card is not None
    issued_at = int(now_aware.timestamp())
    lease_expires = now_aware + timedelta(seconds=soft.lease_ttl_seconds)
    claims = {
        "iss": settings.public_base_url,
        "aud": soft.software_id,
        "sub": card.auth_id,
        "installationId": data["installationId"],
        "deviceKeyThumbprint": device_key_thumbprint,
        "clientVersion": data["clientVersion"],
        "status": "active",
        "iat": issued_at,
        "nbf": issued_at,
        "exp": int(lease_expires.timestamp()),
        "jti": secrets.token_hex(16),
        "protocolVersion": 2,
        "policyVersion": soft.policy_version,
        "updateAvailable": version_data["updateAvailable"],
        "updateRequired": version_data["updateRequired"],
        "latestVersion": version_data["latestVersion"],
        "minimumVersion": version_data["minimumVersion"],
    }
    try:
        lease_token = sign_jws(claims)
    except Exception:
        db.rollback()
        return api_error("SERVICE_UNAVAILABLE", "授权签名服务暂不可用", 503, retryable=True, request_id=request_id)

    soft.visit += 1
    soft.lasttime = now
    soft.last_protocol_version = 2
    soft.last_client_version = data["clientVersion"]
    soft.last_protocol_at = now
    add_v2_audit(
        db,
        request,
        request_id,
        data,
        "LICENSE_VALID",
        owner_id=soft.owner_id,
        card=card,
        device_thumbprint=device_key_thumbprint,
    )
    db.commit()
    payload = {
        "status": "active",
        "expiresAt": utc_text(card.end_time) if card.end_time else None,
        "serverTime": utc_text(now_aware),
        "nextCheckAfterSeconds": soft.next_check_after_seconds,
        "offlineGraceSeconds": 0,
        "requiresOnline": True,
        "leaseExpiresAt": utc_text(lease_expires),
        "leaseToken": lease_token,
        "updateAvailable": version_data["updateAvailable"],
        "updateRequired": version_data["updateRequired"],
        "latestVersion": version_data["latestVersion"],
        "minimumVersion": version_data["minimumVersion"],
    }
    return ok(payload)


@app.post("/api/client/cloudVariables/list", deprecated=True)
def client_cloud_vars(body: AnyBody, db: Session = Depends(get_db)):
    data = body_dict(body)
    soft, error = client_software_or_fail(db, data)
    if not soft:
        return fail(error)
    rows = db.query(CloudVariable).filter(CloudVariable.owner_id == soft.owner_id, CloudVariable.status == "y", CloudVariable.software_id.in_(["", soft.software_id])).all()
    return ok([cloud_var_dict(row) for row in rows])


@app.post("/api/client/user/register", deprecated=True)
def client_user_register(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    ip = request_ip(request) or "unknown"
    if not rate_limiter.allow(f"client-register:{ip}", 20, 3600):
        return fail("请求过于频繁", status_code=429, error_code="RATE_LIMITED", retryable=True)
    soft, error = client_software_or_fail(db, data)
    if not soft:
        return fail(error)
    owner_id = soft.owner_id
    if db.query(Customer).filter(Customer.owner_id == owner_id, Customer.email == data.get("email")).first():
        return fail("邮箱已注册")
    customer = Customer(
        owner_id=owner_id,
        customer_id=random_code("CU", 14),
        email=data.get("email"),
        password_hash=hash_password(data.get("password") or ""),
        nick_name=data.get("nickName") or data.get("email"),
        keys=json.dumps({data.get("softwareId"): "registered"}, ensure_ascii=False),
    )
    db.add(customer)
    add_event(db, owner_id, "api", "userRegister", "用户注册", request, software_id=data.get("softwareId"), customer_id=customer.customer_id)
    db.commit()
    return ok(customer_dict(customer))


@app.post("/api/client/user/login", deprecated=True)
def client_user_login(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    ip = request_ip(request) or "unknown"
    if not rate_limiter.allow(f"client-login:{ip}", 60, 60):
        return fail("请求过于频繁", status_code=429, error_code="RATE_LIMITED", retryable=True)
    soft, error = client_software_or_fail(db, data)
    if not soft:
        return fail(error)
    owner_id = soft.owner_id if soft else None
    customer = db.query(Customer).filter(Customer.owner_id == owner_id, Customer.email == data.get("email")).first() if owner_id else None
    if not customer or not verify_password(data.get("password") or "", customer.password_hash):
        add_event(db, owner_id, "security", "userLogin", "软件用户登录失败", request, result="failed", software_id=data.get("softwareId"))
        db.commit()
        return fail("邮箱或密码错误")
    customer.last_login = datetime.utcnow()
    add_event(db, owner_id, "api", "userLogin", "用户登录", request, software_id=data.get("softwareId"), customer_id=customer.customer_id)
    db.commit()
    return ok(customer_dict(customer))


@app.post("/api/client/user/heartbeat", deprecated=True)
def client_user_heartbeat(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    soft, error = client_software_or_fail(db, data)
    if not soft:
        return fail(error)
    owner_id = soft.owner_id if soft else None
    add_event(db, owner_id, "api", "heartbeat", "用户心跳", request, software_id=data.get("softwareId"), customer_id=data.get("customerId"), macid=data.get("macid"))
    db.commit()
    return ok({"serverTime": datetime.utcnow().isoformat()})


@app.post("/api/client/user/logout", deprecated=True)
def client_user_logout(body: AnyBody, request: Request, db: Session = Depends(get_db)):
    data = body_dict(body)
    soft, error = client_software_or_fail(db, data)
    if not soft:
        return fail(error)
    owner_id = soft.owner_id if soft else None
    add_event(db, owner_id, "api", "userLogout", "用户退出", request, software_id=data.get("softwareId"), customer_id=data.get("customerId"))
    db.commit()
    return ok()
