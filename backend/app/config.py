import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    secret_key: str
    token_expire_minutes: int
    default_admin_user: str
    default_admin_password: str
    default_admin_email: str
    allow_dev_reset_link: bool


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("CARD_APP_NAME", "Card System"),
        database_url=os.getenv("CARD_DATABASE_URL", "sqlite:///./card_system.db"),
        secret_key=os.getenv("CARD_SECRET_KEY", "change-me-in-production"),
        token_expire_minutes=int(os.getenv("CARD_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7))),
        default_admin_user=os.getenv("CARD_DEFAULT_ADMIN_USER", "admin"),
        default_admin_password=os.getenv("CARD_DEFAULT_ADMIN_PASSWORD", "admin123456"),
        default_admin_email=os.getenv("CARD_DEFAULT_ADMIN_EMAIL", "admin@example.com"),
        allow_dev_reset_link=os.getenv("CARD_ALLOW_DEV_RESET_LINK", "true").lower() == "true",
    )
