"""Add public campaigns and user-owned donation notifications.

Revision ID: 8c41d62a9f30
Revises: 3e1c449879e2
"""

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8c41d62a9f30"
down_revision: Union[str, None] = "3e1c449879e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _as_datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _as_date(value):
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _campaign_slug(title: str, campaign_id: int, used: set[str]) -> str:
    base = re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "", title).strip().lower())
    base = base[:220].strip("-") or f"community-campaign-{campaign_id}"
    slug = base
    suffix = 2
    while slug in used:
        suffix_text = f"-{suffix}"
        slug = f"{base[: 255 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    used.add(slug)
    return slug


def _create_index_if_missing(
    connection,
    name: str,
    table: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    inspector = sa.inspect(connection)
    if not any(index["name"] == name for index in inspector.get_indexes(table)):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if not inspector.has_table("campaign"):
        op.create_table(
            "campaign",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("slug", sa.String(length=255), nullable=False),
            sa.Column("summary", sa.String(), nullable=False),
            sa.Column("story", sa.String(), nullable=False),
            sa.Column("image_url", sa.String(length=2048), nullable=True),
            sa.Column("image_alt", sa.String(length=500), nullable=True),
            sa.Column("area", sa.String(length=255), nullable=False),
            sa.Column("category", sa.String(length=100), nullable=False),
            sa.Column("target_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column(
                "legacy_raised_amount",
                sa.Numeric(12, 2),
                nullable=False,
                server_default="0.00",
            ),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("completion_return_status", sa.String(length=50), nullable=True),
            sa.Column("deadline", sa.Date(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("legacy_need_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["legacy_need_id"], ["beneficiaryneed.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns, unique in (
        ("ix_campaign_slug", ["slug"], True),
        ("ix_campaign_status", ["status"], False),
        ("ix_campaign_deadline", ["deadline"], False),
        ("ix_campaign_created_by", ["created_by"], False),
        ("ix_campaign_legacy_need_id", ["legacy_need_id"], False),
        ("ix_campaign_published_at", ["published_at"], False),
        ("ix_campaign_completed_at", ["completed_at"], False),
        ("ix_campaign_archived_at", ["archived_at"], False),
    ):
        _create_index_if_missing(connection, name, "campaign", columns, unique=unique)

    donation_columns = {
        column["name"] for column in sa.inspect(connection).get_columns("donation")
    }
    missing_donation_columns = {"campaign_id", "user_id"} - donation_columns
    if missing_donation_columns:
        with op.batch_alter_table("donation") as batch_op:
            if "campaign_id" in missing_donation_columns:
                batch_op.add_column(
                    sa.Column("campaign_id", sa.Integer(), nullable=True)
                )
                batch_op.create_foreign_key(
                    "fk_donation_campaign_id_campaign",
                    "campaign",
                    ["campaign_id"],
                    ["id"],
                )
            if "user_id" in missing_donation_columns:
                batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
                batch_op.create_foreign_key(
                    "fk_donation_user_id_user",
                    "user",
                    ["user_id"],
                    ["id"],
                )
    _create_index_if_missing(
        connection, "ix_donation_campaign_id", "donation", ["campaign_id"]
    )
    _create_index_if_missing(connection, "ix_donation_user_id", "donation", ["user_id"])

    if not sa.inspect(connection).has_table("usernotification"):
        op.create_table(
            "usernotification",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("donation_id", sa.Integer(), nullable=True),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column("message", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"]),
            sa.ForeignKeyConstraint(["donation_id"], ["donation.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in (
        ("ix_usernotification_user_id", ["user_id"]),
        ("ix_usernotification_donation_id", ["donation_id"]),
        ("ix_usernotification_campaign_id", ["campaign_id"]),
        ("ix_usernotification_event_type", ["event_type"]),
        ("ix_usernotification_read_at", ["read_at"]),
        ("ix_usernotification_user_created", ["user_id", "created_at"]),
    ):
        _create_index_if_missing(connection, name, "usernotification", columns)

    existing_legacy_need_ids = {
        row[0]
        for row in connection.execute(
            sa.text(
                "SELECT legacy_need_id FROM campaign WHERE legacy_need_id IS NOT NULL"
            )
        )
    }
    existing_slugs = {
        row[0] for row in connection.execute(sa.text("SELECT slug FROM campaign"))
    }
    # Materialize the result set before issuing any additional commands on the
    # same connection. SQL Server ODBC rejects a second statement while a
    # previous result set is still open.
    needs = list(
        connection.execute(
            sa.text(
                "SELECT id, anonymised_title, area, category, request_details, "
                "target_amount, current_amount, status, deadline, created_at, "
                "closed_at, archived_at FROM beneficiaryneed "
                "WHERE is_community_need = 1"
            )
        ).mappings()
    )
    campaign_table = sa.Table(
        "campaign",
        sa.MetaData(),
        autoload_with=connection,
    )
    used_slugs = set(existing_slugs)
    for need in needs:
        need_id = need["id"]
        if need_id in existing_legacy_need_ids:
            continue
        title = (need["anonymised_title"] or "").strip() or f"Community need {need_id}"
        area = (need["area"] or "").strip() or "Community"
        details = (need["request_details"] or "").strip()
        status = str(need["status"])
        archived_at = _as_datetime(need["archived_at"])
        target_amount = Decimal(str(need["target_amount"] or "0.00"))
        legacy_raised = Decimal(str(need["current_amount"] or "0.00"))
        completed = status in {"Fulfilled", "NeedStatus.FULFILLED"} or (
            target_amount > Decimal("0.00") and legacy_raised >= target_amount
        )
        archived = archived_at is not None or status in {
            "Rejected",
            "NeedStatus.REJECTED",
        }
        campaign_status = (
            "ARCHIVED" if archived else "COMPLETED" if completed else "PUBLISHED"
        )
        created_at = _as_datetime(need["created_at"]) or datetime.now(timezone.utc)
        campaign_id = int(need_id)
        connection.execute(
            campaign_table.insert().values(
                title=title[:255],
                slug=_campaign_slug(title, campaign_id, used_slugs),
                summary=(details or f"Supporting {title} in {area}."),
                story=details
                or f"Staff are coordinating support for {title} in {area}.",
                area=area[:255],
                category=(need["category"] or "Community")[:100],
                target_amount=target_amount,
                legacy_raised_amount=legacy_raised,
                status=campaign_status,
                completion_return_status=(
                    "Published" if campaign_status == "COMPLETED" else None
                ),
                deadline=_as_date(need["deadline"]),
                legacy_need_id=need_id,
                created_at=created_at,
                published_at=created_at if campaign_status != "ARCHIVED" else None,
                completed_at=(
                    _as_datetime(need["closed_at"]) or created_at if completed else None
                ),
                archived_at=archived_at if archived else None,
            )
        )


def downgrade() -> None:
    raise RuntimeError(
        "This data migration is irreversible; restore a backup or add a forward migration."
    )
