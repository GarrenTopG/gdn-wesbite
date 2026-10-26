"""Add shared Google and Microsoft SSO records.

Revision ID: a4d85d1c6f20
Revises: 9f89a4e2cc71
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a4d85d1c6f20"
down_revision: Union[str, None] = "9f89a4e2cc71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("externalidentity"):
        op.create_table(
            "externalidentity",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=30), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "subject"),
        )
    if not sa.inspect(connection).has_table("ssotransaction"):
        op.create_table(
            "ssotransaction",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("state_hash", sa.String(length=64), nullable=False),
            sa.Column("provider", sa.String(length=30), nullable=False),
            sa.Column("client_type", sa.String(length=10), nullable=False),
            sa.Column("intent", sa.String(length=10), nullable=False),
            sa.Column("next_path", sa.String(length=2048), nullable=False),
            sa.Column("nonce", sa.String(length=128), nullable=False),
            sa.Column("provider_code_verifier", sa.String(length=128), nullable=False),
            sa.Column("mobile_code_challenge", sa.String(length=128), nullable=True),
            sa.Column("link_user_id", sa.Integer(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["link_user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not sa.inspect(connection).has_table("mobilessocode"):
        op.create_table(
            "mobilessocode",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("code_challenge", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for table, indexes in (
        (
            "externalidentity",
            (
                ("ix_externalidentity_user_id", ["user_id"], False),
                ("ix_externalidentity_provider", ["provider"], False),
            ),
        ),
        (
            "ssotransaction",
            (
                ("ix_ssotransaction_state_hash", ["state_hash"], True),
                ("ix_ssotransaction_provider", ["provider"], False),
                ("ix_ssotransaction_expires_at", ["expires_at"], False),
            ),
        ),
        (
            "mobilessocode",
            (
                ("ix_mobilessocode_code_hash", ["code_hash"], True),
                ("ix_mobilessocode_user_id", ["user_id"], False),
                ("ix_mobilessocode_expires_at", ["expires_at"], False),
                ("ix_mobilessocode_consumed_at", ["consumed_at"], False),
            ),
        ),
    ):
        existing = {item["name"] for item in sa.inspect(connection).get_indexes(table)}
        for name, columns, unique in indexes:
            if name not in existing:
                op.create_index(name, table, columns, unique=unique)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("mobilessocode", "ssotransaction", "externalidentity"):
        if inspector.has_table(table):
            op.drop_table(table)
