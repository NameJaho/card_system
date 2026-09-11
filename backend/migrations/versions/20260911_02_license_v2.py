"""Add signed v2 leases, device proof, nonce replay defense, and HMAC license lookup."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import string

from alembic import op
import sqlalchemy as sa


revision = "20260911_02"
down_revision = "20260910_01"
branch_labels = None
depends_on = None


def _columns(inspector: sa.Inspector, table: str) -> dict[str, dict]:
    return {column["name"]: column for column in inspector.get_columns(table)}


def _pepper() -> str:
    value = os.getenv("CARD_LICENSE_PEPPER", "").strip()
    environment = os.getenv("CARD_ENV", "development").strip().lower()
    if not value and environment not in {"production", "prod"}:
        value = "development-only-license-pepper"
    if not value or (environment in {"production", "prod"} and (value == "development-only-license-pepper" or len(value) < 32)):
        raise RuntimeError("CARD_LICENSE_PEPPER must be configured before the v2 migration")
    return value


def _lookup(value: str, pepper: str) -> str:
    normalized = str(value or "").strip().upper()
    return hmac.new(pepper.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def _card_ref() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "CARD_" + "".join(secrets.choice(alphabet) for _ in range(24))


def _create_tables(inspector: sa.Inspector) -> None:
    tables = set(inspector.get_table_names())
    if "license_request_nonces" not in tables:
        op.create_table(
            "license_request_nonces",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nonce_hash", sa.String(64), nullable=False),
            sa.Column("software_id", sa.String(80), nullable=False),
            sa.Column("request_id", sa.String(80), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("nonce_hash", name="uq_license_request_nonce_hash"),
            sa.UniqueConstraint("request_id", name="uq_license_request_nonce_request_id"),
        )
        op.create_index("ix_license_request_nonces_nonce_hash", "license_request_nonces", ["nonce_hash"])
        op.create_index("ix_license_request_nonces_software_id", "license_request_nonces", ["software_id"])
        op.create_index("ix_license_request_nonces_request_id", "license_request_nonces", ["request_id"])
        op.create_index("ix_license_request_nonces_expires_at", "license_request_nonces", ["expires_at"])
    if "license_audit_events" not in tables:
        op.create_table(
            "license_audit_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
            sa.Column("request_id", sa.String(80), nullable=False),
            sa.Column("event_type", sa.String(60), nullable=False),
            sa.Column("software_id", sa.String(80), nullable=False),
            sa.Column("license_ref", sa.String(120), nullable=True),
            sa.Column("license_last4", sa.String(4), nullable=True),
            sa.Column("installation_hash", sa.String(64), nullable=False),
            sa.Column("device_key_thumbprint", sa.String(64), nullable=True),
            sa.Column("client_version", sa.String(80), nullable=False),
            sa.Column("protocol_version", sa.Integer(), nullable=False),
            sa.Column("result_code", sa.String(80), nullable=False),
            sa.Column("source_ip", sa.String(80), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("request_id", name="uq_license_audit_request_id"),
        )
        op.create_index("ix_license_audit_events_owner_id", "license_audit_events", ["owner_id"])
        op.create_index("ix_license_audit_events_request_id", "license_audit_events", ["request_id"])
        op.create_index("ix_license_audit_events_software_id", "license_audit_events", ["software_id"])
        op.create_index("ix_license_audit_events_result_code", "license_audit_events", ["result_code"])
        op.create_index("ix_license_audit_events_created_at", "license_audit_events", ["created_at"])
    if "license_signing_keys" not in tables:
        op.create_table(
            "license_signing_keys",
            sa.Column("kid", sa.String(80), primary_key=True),
            sa.Column("public_key", sa.String(120), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("not_before", sa.DateTime(), nullable=True),
            sa.Column("not_after", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_license_signing_keys_status", "license_signing_keys", ["status"])


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _create_tables(inspector)

    software_columns = _columns(sa.inspect(bind), "software_instances")
    software_fields = (
        ("minimum_protocol_version", sa.Integer(), "1"),
        ("lease_ttl_seconds", sa.Integer(), "300"),
        ("next_check_after_seconds", sa.Integer(), "60"),
        ("offline_grace_seconds", sa.Integer(), "0"),
        ("device_proof_required", sa.Boolean(), sa.true()),
        ("policy_version", sa.Integer(), "1"),
    )
    for name, type_, default in software_fields:
        if name not in software_columns:
            op.add_column("software_instances", sa.Column(name, type_, nullable=False, server_default=default))
    for name, type_ in (
        ("last_protocol_version", sa.Integer()),
        ("last_client_version", sa.String(80)),
        ("last_protocol_at", sa.DateTime()),
    ):
        if name not in software_columns:
            op.add_column("software_instances", sa.Column(name, type_, nullable=True))

    auth_columns = _columns(sa.inspect(bind), "auth_cards")
    for name, type_ in (
        ("license_lookup", sa.String(64)),
        ("license_last4", sa.String(4)),
        ("device_public_key", sa.Text()),
        ("device_key_thumbprint", sa.String(64)),
        ("revoked_at", sa.DateTime()),
    ):
        if name not in auth_columns:
            op.add_column("auth_cards", sa.Column(name, type_, nullable=True))
    if "protocol_version" not in auth_columns:
        op.add_column("auth_cards", sa.Column("protocol_version", sa.Integer(), nullable=False, server_default="1"))

    pepper = _pepper()
    rows = bind.execute(sa.text("SELECT id, auth_id, license_lookup, license_last4 FROM auth_cards ORDER BY id")).mappings().all()
    used_refs = {str(row["auth_id"]) for row in rows if str(row["auth_id"] or "").startswith("CARD_")}
    has_event_logs = "event_logs" in set(sa.inspect(bind).get_table_names())
    for row in rows:
        original = str(row["auth_id"] or "").strip()
        existing_lookup = str(row["license_lookup"] or "").strip().lower()
        existing_last4 = str(row["license_last4"] or "").strip().upper()
        if original.startswith("CARD_"):
            if len(existing_lookup) != 64 or any(character not in string.hexdigits for character in existing_lookup) or len(existing_last4) != 4:
                raise RuntimeError(
                    f"auth_cards.id={row['id']} is partially migrated and the original license is unavailable; restore the pre-migration backup"
                )
            continue
        if len(original) < 4:
            raise RuntimeError(f"auth_cards.id={row['id']} contains an invalid license value")
        normalized = original.upper()
        expected_lookup = _lookup(normalized, pepper)
        if existing_lookup and not hmac.compare_digest(existing_lookup, expected_lookup):
            raise RuntimeError(
                f"auth_cards.id={row['id']} lookup does not match CARD_LICENSE_PEPPER; restore the original pepper before migration"
            )
        reference = _card_ref()
        while reference in used_refs:
            reference = _card_ref()
        used_refs.add(reference)
        if has_event_logs:
            bind.execute(
                sa.text("UPDATE event_logs SET auth_id=:reference WHERE auth_id=:original"),
                {"reference": reference, "original": original},
            )
        bind.execute(
            sa.text(
                "UPDATE auth_cards SET auth_id=:reference, license_lookup=:lookup, license_last4=:last4 "
                "WHERE id=:id"
            ),
            {"reference": reference, "lookup": expected_lookup, "last4": existing_last4 or normalized[-4:], "id": row["id"]},
        )

    if has_event_logs:
        event_rows = bind.execute(sa.text("SELECT id, auth_id FROM event_logs WHERE auth_id IS NOT NULL")).mappings().all()
        for event in event_rows:
            value = str(event["auth_id"] or "").strip()
            if value.upper().startswith("KM") and not value.startswith(("hmac:", "sha256:", "last4:")):
                redacted = f"hmac:{_lookup(value, pepper)[:12]}:last4:{value[-4:].upper()}"
                bind.execute(
                    sa.text("UPDATE event_logs SET auth_id=:redacted WHERE id=:id"),
                    {"redacted": redacted, "id": event["id"]},
                )

    inspector = sa.inspect(bind)
    auth_columns = _columns(inspector, "auth_cards")
    unique_constraints = inspector.get_unique_constraints("auth_cards")
    uniques = {item.get("name") for item in unique_constraints}
    unique_columns = {tuple(item.get("column_names") or []) for item in unique_constraints}
    indexes = {item.get("name") for item in inspector.get_indexes("auth_cards")}
    with op.batch_alter_table("auth_cards") as batch:
        if auth_columns["license_lookup"].get("nullable", True):
            batch.alter_column("license_lookup", existing_type=sa.String(64), nullable=False)
        if auth_columns["license_last4"].get("nullable", True):
            batch.alter_column("license_last4", existing_type=sa.String(4), nullable=False)
        if "uq_auth_cards_license_lookup" not in uniques and ("license_lookup",) not in unique_columns:
            batch.create_unique_constraint("uq_auth_cards_license_lookup", ["license_lookup"])
        if "ix_auth_cards_device_key_thumbprint" not in indexes:
            batch.create_index("ix_auth_cards_device_key_thumbprint", ["device_key_thumbprint"])


def downgrade() -> None:
    raise RuntimeError("20260911_02 removes plaintext license keys; restore the pre-release database backup instead")
