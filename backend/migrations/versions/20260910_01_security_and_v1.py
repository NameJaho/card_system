"""Backfill instance keys and add security/v1 protocol fields."""
from __future__ import annotations

import secrets
import string

from alembic import op
import sqlalchemy as sa

from app.database import Base
from app import models  # noqa: F401


revision = "20260910_01"
down_revision = None
branch_labels = None
depends_on = None


def _columns(inspector: sa.Inspector, table: str) -> dict[str, dict]:
    return {column["name"]: column for column in inspector.get_columns(table)}


def _instance_key() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "IK" + "".join(secrets.choice(alphabet) for _ in range(32))


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    inspector = sa.inspect(bind)

    admin_columns = _columns(inspector, "admin_users")
    if "role" not in admin_columns:
        op.add_column("admin_users", sa.Column("role", sa.String(30), nullable=True))
    bind.execute(
        sa.text(
            "UPDATE admin_users SET role = CASE WHEN parent_id IS NULL THEN 'admin' ELSE 'user' END "
            "WHERE role IS NULL OR role = ''"
        )
    )
    if "token_version" not in admin_columns:
        op.add_column("admin_users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))

    auth_columns = _columns(inspector, "auth_cards")
    if "creator_id" not in auth_columns:
        op.add_column("auth_cards", sa.Column("creator_id", sa.Integer(), nullable=True))
    if "creator_user" not in auth_columns:
        op.add_column("auth_cards", sa.Column("creator_user", sa.String(80), nullable=False, server_default=""))
    if "creator_role" not in auth_columns:
        op.add_column("auth_cards", sa.Column("creator_role", sa.String(30), nullable=False, server_default="user"))
    bind.execute(sa.text("UPDATE auth_cards SET creator_id = owner_id WHERE creator_id IS NULL"))
    bind.execute(
        sa.text(
            "UPDATE auth_cards SET creator_user = COALESCE((SELECT admin_users.user FROM admin_users WHERE admin_users.id = auth_cards.creator_id), '') "
            "WHERE creator_user IS NULL OR creator_user = ''"
        )
    )
    if "private_key" in auth_columns:
        with op.batch_alter_table("auth_cards") as batch:
            batch.drop_column("private_key")
    bind.execute(
        sa.text(
            "UPDATE auth_cards SET creator_role = COALESCE((SELECT admin_users.role FROM admin_users WHERE admin_users.id = auth_cards.creator_id), 'user') "
            "WHERE creator_role IS NULL OR creator_role = ''"
        )
    )

    software_columns = _columns(inspector, "software_instances")
    if "instance_key" not in software_columns:
        op.add_column("software_instances", sa.Column("instance_key", sa.String(80), nullable=True))
    if "protocol_version" not in software_columns:
        op.add_column("software_instances", sa.Column("protocol_version", sa.String(20), nullable=False, server_default="v1"))
    if "strict_client_auth" not in software_columns:
        op.add_column("software_instances", sa.Column("strict_client_auth", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "sha256" not in software_columns:
        op.add_column("software_instances", sa.Column("sha256", sa.String(64), nullable=True))

    rows = bind.execute(sa.text("SELECT id, instance_key FROM software_instances ORDER BY id")).fetchall()
    seen: set[str] = set()
    for row in rows:
        value = str(row.instance_key or "").strip()
        if not value or value in seen:
            value = _instance_key()
            while value in seen:
                value = _instance_key()
            bind.execute(
                sa.text("UPDATE software_instances SET instance_key = :instance_key WHERE id = :id"),
                {"instance_key": value, "id": row.id},
            )
        seen.add(value)

    inspector = sa.inspect(bind)
    checks = {item.get("name") for item in inspector.get_check_constraints("software_instances")}
    unique_constraints = {item.get("name") for item in inspector.get_unique_constraints("software_instances")}
    instance_column = _columns(inspector, "software_instances")["instance_key"]
    with op.batch_alter_table("software_instances") as batch:
        if instance_column.get("nullable", True):
            batch.alter_column("instance_key", existing_type=sa.String(80), nullable=False)
        if "ck_software_instance_key_not_blank" not in checks:
            batch.create_check_constraint("ck_software_instance_key_not_blank", "length(trim(instance_key)) > 0")
        if "uq_software_instance_key" not in unique_constraints:
            batch.create_unique_constraint("uq_software_instance_key", ["instance_key"])


def downgrade() -> None:
    op.add_column("auth_cards", sa.Column("private_key", sa.String(80), nullable=True))
    with op.batch_alter_table("software_instances") as batch:
        batch.drop_constraint("uq_software_instance_key", type_="unique")
        batch.drop_constraint("ck_software_instance_key_not_blank", type_="check")
        batch.alter_column("instance_key", existing_type=sa.String(80), nullable=True)
        batch.drop_column("sha256")
        batch.drop_column("strict_client_auth")
        batch.drop_column("protocol_version")
    op.drop_column("admin_users", "token_version")
