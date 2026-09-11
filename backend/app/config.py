import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    environment: str
    app_name: str
    database_url: str
    secret_key: str
    token_expire_minutes: int
    default_admin_user: str
    default_admin_password: str
    default_admin_email: str
    allow_dev_reset_link: bool
    public_base_url: str
    app_version: str
    git_sha: str
    schema_version: str
    password_reset_minutes: int
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_starttls: bool
    cors_origins: tuple[str, ...]
    license_signing_key_file: str
    license_signing_key_id: str
    license_previous_public_keys: str
    license_pepper: str
    license_lease_ttl_seconds: int
    license_next_check_seconds: int
    license_request_window_seconds: int
    license_nonce_ttl_seconds: int
    license_audit_retention_days: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        environment=os.getenv("CARD_ENV", "development").strip().lower(),
        app_name=os.getenv("CARD_APP_NAME", "Card System"),
        database_url=os.getenv("CARD_DATABASE_URL", "sqlite:///./card_system.db"),
        secret_key=os.getenv("CARD_SECRET_KEY", "change-me-in-production"),
        token_expire_minutes=int(os.getenv("CARD_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7))),
        default_admin_user=os.getenv("CARD_DEFAULT_ADMIN_USER", "admin"),
        default_admin_password=os.getenv("CARD_DEFAULT_ADMIN_PASSWORD", "admin123456"),
        default_admin_email=os.getenv("CARD_DEFAULT_ADMIN_EMAIL", "admin@example.com"),
        allow_dev_reset_link=os.getenv("CARD_ALLOW_DEV_RESET_LINK", "false").lower() == "true",
        public_base_url=os.getenv("CARD_PUBLIC_BASE_URL", "http://127.0.0.1:8080").rstrip("/"),
        app_version=os.getenv("CARD_APP_VERSION", "dev"),
        git_sha=os.getenv("CARD_GIT_SHA", "unknown"),
        schema_version=os.getenv("CARD_SCHEMA_VERSION", "20260911_02"),
        password_reset_minutes=int(os.getenv("CARD_PASSWORD_RESET_MINUTES", "30")),
        smtp_host=os.getenv("CARD_SMTP_HOST", ""),
        smtp_port=int(os.getenv("CARD_SMTP_PORT", "587")),
        smtp_user=os.getenv("CARD_SMTP_USER", ""),
        smtp_password=os.getenv("CARD_SMTP_PASSWORD", ""),
        smtp_from=os.getenv("CARD_SMTP_FROM", ""),
        smtp_starttls=os.getenv("CARD_SMTP_STARTTLS", "true").lower() == "true",
        cors_origins=tuple(
            origin.strip()
            for origin in os.getenv("CARD_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if origin.strip()
        ),
        license_signing_key_file=os.getenv("CARD_LICENSE_SIGNING_KEY_FILE", "").strip(),
        license_signing_key_id=os.getenv("CARD_LICENSE_SIGNING_KEY_ID", "license-dev-01").strip(),
        license_previous_public_keys=os.getenv("CARD_LICENSE_PREVIOUS_PUBLIC_KEYS", "{}").strip(),
        license_pepper=os.getenv("CARD_LICENSE_PEPPER", "development-only-license-pepper").strip(),
        license_lease_ttl_seconds=int(os.getenv("CARD_LICENSE_LEASE_TTL_SECONDS", "300")),
        license_next_check_seconds=int(os.getenv("CARD_LICENSE_NEXT_CHECK_SECONDS", "60")),
        license_request_window_seconds=int(os.getenv("CARD_LICENSE_REQUEST_WINDOW_SECONDS", "120")),
        license_nonce_ttl_seconds=int(os.getenv("CARD_LICENSE_NONCE_TTL_SECONDS", "600")),
        license_audit_retention_days=int(os.getenv("CARD_LICENSE_AUDIT_RETENTION_DAYS", "90")),
    )


def validate_production_settings(settings: Settings) -> None:
    if settings.environment not in {"production", "prod"}:
        return
    errors = []
    if settings.secret_key in {"change-me-in-production", "change-this-secret", "please-change-this-to-a-long-random-value"} or len(settings.secret_key) < 32:
        errors.append("CARD_SECRET_KEY 必须是至少 32 位的随机值")
    if settings.default_admin_password in {"admin123456", "password", "please-change-admin-password"} or len(settings.default_admin_password) < 12:
        errors.append("CARD_DEFAULT_ADMIN_PASSWORD 必须修改且至少 12 位")
    if not settings.public_base_url.startswith("https://"):
        errors.append("CARD_PUBLIC_BASE_URL 在生产环境必须使用 HTTPS")
    if ":card_password@" in settings.database_url or ":please-change-card-user-password@" in settings.database_url:
        errors.append("CARD_DATABASE_URL 仍在使用示例数据库密码")
    if settings.allow_dev_reset_link:
        errors.append("生产环境禁止 CARD_ALLOW_DEV_RESET_LINK=true")
    if not settings.license_signing_key_file or not Path(settings.license_signing_key_file).is_file():
        errors.append("CARD_LICENSE_SIGNING_KEY_FILE 必须指向可读的 Ed25519 私钥文件")
    if not settings.license_signing_key_id or settings.license_signing_key_id == "license-dev-01":
        errors.append("CARD_LICENSE_SIGNING_KEY_ID 必须设置为生产密钥 ID")
    if settings.license_pepper == "development-only-license-pepper" or len(settings.license_pepper) < 32:
        errors.append("CARD_LICENSE_PEPPER 必须是至少 32 位的独立高熵 secret")
    if not 30 <= settings.license_lease_ttl_seconds <= 900:
        errors.append("CARD_LICENSE_LEASE_TTL_SECONDS 必须在 30 到 900 秒之间")
    if not 10 <= settings.license_next_check_seconds <= settings.license_lease_ttl_seconds:
        errors.append("CARD_LICENSE_NEXT_CHECK_SECONDS 必须在 10 秒和 lease TTL 之间")
    if not 7 <= settings.license_audit_retention_days <= 3650:
        errors.append("CARD_LICENSE_AUDIT_RETENTION_DAYS 必须在 7 到 3650 天之间")
    if errors:
        raise RuntimeError("生产配置不安全: " + "; ".join(errors))
