from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class AuthStatus(str, Enum):
    unused = "unused"
    active = "active"
    expired = "expired"
    disabled = "disabled"
    revoked = "revoked"


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    user: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), default="")
    nick: Mapped[str] = mapped_column(String(120), default="")
    qq: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_token: Mapped[str] = mapped_column(String(80), unique=True)
    open_id: Mapped[str] = mapped_column(String(80), unique=True)
    finger_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(30), default="user")
    permission_types: Mapped[str] = mapped_column(Text, default="[]")
    software_ids: Mapped[str] = mapped_column(Text, default='["*"]')
    is_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    parent: Mapped[AdminUser | None] = relationship(remote_side=[id])


class SoftwareInstance(Base):
    __tablename__ = "software_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(80), default="1.0.0")
    low_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    software_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    instance_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    protocol_version: Mapped[str] = mapped_column(String(20), default="v1", nullable=False)
    strict_client_auth: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    minimum_protocol_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    lease_ttl_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    next_check_after_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    offline_grace_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    device_proof_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_protocol_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_client_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_protocol_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    force: Mapped[bool] = mapped_column(Boolean, default=False)
    remark: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice: Mapped[str] = mapped_column(Text, default="")
    md5: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    visit: Mapped[int] = mapped_column(Integer, default=0)
    gitcode_project_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    gitcode_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    gitcode_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gitcode_repo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    lasttime: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner: Mapped[AdminUser] = relationship()

    __table_args__ = (
        CheckConstraint("length(trim(instance_key)) > 0", name="ck_software_instance_key_not_blank"),
        UniqueConstraint("instance_key", name="uq_software_instance_key"),
    )


class AuthCard(Base):
    __tablename__ = "auth_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    software_id: Mapped[str] = mapped_column(String(80), index=True)
    auth_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    license_lookup: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    license_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=AuthStatus.unused.value)
    macid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bind_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bind_used: Mapped[int] = mapped_column(Integer, default=0)
    day: Mapped[int] = mapped_column(Integer, default=0)
    hour: Mapped[int] = mapped_column(Integer, default=0)
    minute: Mapped[int] = mapped_column(Integer, default=0)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(Text, default="")
    assigned_sub_user: Mapped[str | None] = mapped_column(String(80), nullable=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True, index=True)
    creator_user: Mapped[str] = mapped_column(String(80), default="")
    creator_role: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    device_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_key_thumbprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    protocol_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("owner_id", "auth_id", name="uq_owner_auth_id"),)

    creator: Mapped[AdminUser | None] = relationship(foreign_keys=[creator_id])


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    customer_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    nick_name: Mapped[str] = mapped_column(String(120), default="")
    keys: Mapped[str] = mapped_column(Text, default="{}")
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CloudVariable(Base):
    __tablename__ = "cloud_variables"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(1), default="y")
    software_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BlackWhiteItem(Base):
    __tablename__ = "black_white_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    type: Mapped[str] = mapped_column(String(20), default="white")
    value: Mapped[str] = mapped_column(String(255), index=True)
    remark: Mapped[str] = mapped_column(Text, default="")
    software_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    keyword: Mapped[str] = mapped_column(String(255), default="")
    software_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    auth_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    macid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    result: Mapped[str] = mapped_column(String(40), default="success")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    requested_ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[AdminUser] = relationship()


class LicenseRequestNonce(Base):
    __tablename__ = "license_request_nonces"

    id: Mapped[int] = mapped_column(primary_key=True)
    nonce_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    software_id: Mapped[str] = mapped_column(String(80), index=True)
    request_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LicenseAuditEvent(Base):
    __tablename__ = "license_audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60), default="licenseValidate")
    software_id: Mapped[str] = mapped_column(String(80), index=True)
    license_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    license_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    installation_hash: Mapped[str] = mapped_column(String(64), default="")
    device_key_thumbprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_version: Mapped[str] = mapped_column(String(80), default="")
    protocol_version: Mapped[int] = mapped_column(Integer, default=2)
    result_code: Mapped[str] = mapped_column(String(80), index=True)
    source_ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LicenseSigningKey(Base):
    __tablename__ = "license_signing_keys"

    kid: Mapped[str] = mapped_column(String(80), primary_key=True)
    public_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    not_before: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    not_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
