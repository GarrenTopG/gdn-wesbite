"""initial schema

Revision ID: 6041068d476c
Revises:
Create Date: 2026-10-24 07:46:54.835952
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "6041068d476c"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("newsarticle"):
        op.create_table(
            "newsarticle",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "slug", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
            ),
            sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("summary", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("image_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("author", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("is_featured", sa.Boolean(), nullable=False),
            sa.Column("published_date", sa.Date(), nullable=True),
            sa.Column(
                "status", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
            ),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_newsarticle_archived_at"),
            "newsarticle",
            ["archived_at"],
            unique=False,
        )
        op.create_index(
            op.f("ix_newsarticle_slug"), "newsarticle", ["slug"], unique=True
        )
        op.create_index(
            op.f("ix_newsarticle_status"), "newsarticle", ["status"], unique=False
        )
    if not inspector.has_table("ratelimithit"):
        op.create_table(
            "ratelimithit",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "bucket_key",
                sqlmodel.sql.sqltypes.AutoString(length=255),
                nullable=False,
            ),
            sa.Column("occurred_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_ratelimithit_bucket_key"),
            "ratelimithit",
            ["bucket_key"],
            unique=False,
        )
        op.create_index(
            op.f("ix_ratelimithit_occurred_at"),
            "ratelimithit",
            ["occurred_at"],
            unique=False,
        )
    if not inspector.has_table("user"):
        op.create_table(
            "user",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "phone_number",
                sqlmodel.sql.sqltypes.AutoString(length=50),
                nullable=True,
            ),
            sa.Column("preferences", sa.JSON(), nullable=True),
            sa.Column(
                "email", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
            ),
            sa.Column(
                "hashed_password", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column(
                "role",
                sa.Enum(
                    "ADMINISTRATOR",
                    "CASE_WORKER",
                    "FINANCE",
                    "CONTENT_EDITOR",
                    "READ_ONLY",
                    "USER",
                    name="userrole",
                ),
                nullable=False,
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("mfa_secret", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("mfa_last_counter", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_user_email"), "user", ["email"], unique=True)
    if not inspector.has_table("volunteer"):
        op.create_table(
            "volunteer",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("phone", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "email", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
            ),
            sa.Column("skills", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "availability", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("available_days", sa.JSON(), nullable=True),
            sa.Column(
                "assigned_day", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column(
                "status",
                sa.Enum("ACTIVE", "INACTIVE", "ASSIGNED", name="volunteerstatus"),
                nullable=False,
            ),
            sa.Column(
                "onboarding_status",
                sqlmodel.sql.sqltypes.AutoString(length=50),
                nullable=False,
            ),
            sa.Column("next_assignment_at", sa.DateTime(), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_volunteer_archived_at"), "volunteer", ["archived_at"], unique=False
        )
        op.create_index(
            op.f("ix_volunteer_email"), "volunteer", ["email"], unique=False
        )
        op.create_index(
            op.f("ix_volunteer_next_assignment_at"),
            "volunteer",
            ["next_assignment_at"],
            unique=False,
        )
        op.create_index(
            op.f("ix_volunteer_onboarding_status"),
            "volunteer",
            ["onboarding_status"],
            unique=False,
        )
    if not inspector.has_table("auditlog"):
        op.create_table(
            "auditlog",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column(
                "actor_identity",
                sqlmodel.sql.sqltypes.AutoString(length=255),
                nullable=False,
            ),
            sa.Column(
                "action", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False
            ),
            sa.Column(
                "target_type",
                sqlmodel.sql.sqltypes.AutoString(length=100),
                nullable=False,
            ),
            sa.Column(
                "target_id", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True
            ),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("details", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.ForeignKeyConstraint(
                ["actor_id"],
                ["user.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_auditlog_action"), "auditlog", ["action"], unique=False
        )
        op.create_index(
            op.f("ix_auditlog_actor_id"), "auditlog", ["actor_id"], unique=False
        )
        op.create_index(
            op.f("ix_auditlog_actor_identity"),
            "auditlog",
            ["actor_identity"],
            unique=False,
        )
        op.create_index(
            op.f("ix_auditlog_occurred_at"), "auditlog", ["occurred_at"], unique=False
        )
        op.create_index(
            op.f("ix_auditlog_target_id"), "auditlog", ["target_id"], unique=False
        )
        op.create_index(
            op.f("ix_auditlog_target_type"), "auditlog", ["target_type"], unique=False
        )
    if not inspector.has_table("authsession"):
        op.create_table(
            "authsession",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "token_hash",
                sqlmodel.sql.sqltypes.AutoString(length=255),
                nullable=False,
            ),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("mfa_verified", sa.Boolean(), nullable=False),
            sa.Column(
                "mfa_setup_secret", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["user.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_authsession_expires_at"),
            "authsession",
            ["expires_at"],
            unique=False,
        )
        op.create_index(
            op.f("ix_authsession_mfa_verified"),
            "authsession",
            ["mfa_verified"],
            unique=False,
        )
        op.create_index(
            op.f("ix_authsession_token_hash"),
            "authsession",
            ["token_hash"],
            unique=True,
        )
        op.create_index(
            op.f("ix_authsession_user_id"), "authsession", ["user_id"], unique=False
        )
    if not inspector.has_table("beneficiaryneed"):
        op.create_table(
            "beneficiaryneed",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("is_community_need", sa.Boolean(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column(
                "contact_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column(
                "contact_phone", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column(
                "full_address", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column(
                "anonymised_title", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("area", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "request_details", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column(
                "urgency",
                sa.Enum("LOW", "MEDIUM", "HIGH", "CRITICAL", name="needurgency"),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.Enum(
                    "Open",
                    "PENDING",
                    "IN_PROGRESS",
                    "MATCHED",
                    "FULFILLED",
                    "REJECTED",
                    name="needstatus",
                ),
                nullable=False,
            ),
            sa.Column(
                "target_amount", sa.Numeric(precision=12, scale=2), nullable=False
            ),
            sa.Column(
                "current_amount", sa.Numeric(precision=12, scale=2), nullable=False
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("assigned_staff_id", sa.Integer(), nullable=True),
            sa.Column(
                "internal_notes", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column("follow_up_at", sa.DateTime(), nullable=True),
            sa.Column("deadline", sa.DateTime(), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["assigned_staff_id"],
                ["user.id"],
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["user.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_beneficiaryneed_archived_at"),
            "beneficiaryneed",
            ["archived_at"],
            unique=False,
        )
        op.create_index(
            op.f("ix_beneficiaryneed_assigned_staff_id"),
            "beneficiaryneed",
            ["assigned_staff_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_beneficiaryneed_closed_at"),
            "beneficiaryneed",
            ["closed_at"],
            unique=False,
        )
        op.create_index(
            op.f("ix_beneficiaryneed_deadline"),
            "beneficiaryneed",
            ["deadline"],
            unique=False,
        )
        op.create_index(
            op.f("ix_beneficiaryneed_follow_up_at"),
            "beneficiaryneed",
            ["follow_up_at"],
            unique=False,
        )
        op.create_index(
            op.f("ix_beneficiaryneed_is_community_need"),
            "beneficiaryneed",
            ["is_community_need"],
            unique=False,
        )
        op.create_index(
            op.f("ix_beneficiaryneed_status"),
            "beneficiaryneed",
            ["status"],
            unique=False,
        )
        op.create_index(
            op.f("ix_beneficiaryneed_user_id"),
            "beneficiaryneed",
            ["user_id"],
            unique=False,
        )
    if not inspector.has_table("recordhistory"):
        op.create_table(
            "recordhistory",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "record_type",
                sqlmodel.sql.sqltypes.AutoString(length=100),
                nullable=False,
            ),
            sa.Column("record_id", sa.Integer(), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column(
                "action", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False
            ),
            sa.Column("details", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["actor_id"],
                ["user.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_recordhistory_action"), "recordhistory", ["action"], unique=False
        )
        op.create_index(
            op.f("ix_recordhistory_actor_id"),
            "recordhistory",
            ["actor_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_recordhistory_occurred_at"),
            "recordhistory",
            ["occurred_at"],
            unique=False,
        )
        op.create_index(
            op.f("ix_recordhistory_record_id"),
            "recordhistory",
            ["record_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_recordhistory_record_type"),
            "recordhistory",
            ["record_type"],
            unique=False,
        )
    if not inspector.has_table("staffnotificationread"):
        op.create_table(
            "staffnotificationread",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("staff_user_id", sa.Integer(), nullable=False),
            sa.Column(
                "notification_key",
                sqlmodel.sql.sqltypes.AutoString(length=255),
                nullable=False,
            ),
            sa.Column(
                "fingerprint", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["staff_user_id"],
                ["user.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("staff_user_id", "notification_key"),
        )
        op.create_index(
            op.f("ix_staffnotificationread_notification_key"),
            "staffnotificationread",
            ["notification_key"],
            unique=False,
        )
        op.create_index(
            op.f("ix_staffnotificationread_staff_user_id"),
            "staffnotificationread",
            ["staff_user_id"],
            unique=False,
        )
    if not inspector.has_table("donation"):
        op.create_table(
            "donation",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("donor_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "donor_email",
                sqlmodel.sql.sqltypes.AutoString(length=255),
                nullable=True,
            ),
            sa.Column("donor_phone", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("cause", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column(
                "donation_type",
                sqlmodel.sql.sqltypes.AutoString(length=50),
                nullable=False,
            ),
            sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column(
                "allocated_amount", sa.Numeric(precision=12, scale=2), nullable=False
            ),
            sa.Column(
                "item_category", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column(
                "item_description", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column(
                "logistics_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column(
                "pickup_address", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column("request_tax_certificate", sa.Boolean(), nullable=False),
            sa.Column(
                "tax_id_number", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column("tax_address", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column(
                "pending_receipt_token_hash",
                sqlmodel.sql.sqltypes.AutoString(length=255),
                nullable=True,
            ),
            sa.Column(
                "payment_method", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column(
                "proof_of_payment_url",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            ),
            sa.Column("message", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("is_anonymous", sa.Boolean(), nullable=False),
            sa.Column("is_verified", sa.Boolean(), nullable=False),
            sa.Column(
                "status", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
            ),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("need_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["need_id"],
                ["beneficiaryneed.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_donation_archived_at"), "donation", ["archived_at"], unique=False
        )
        op.create_index(
            op.f("ix_donation_donation_type"),
            "donation",
            ["donation_type"],
            unique=False,
        )
        op.create_index(
            op.f("ix_donation_donor_email"), "donation", ["donor_email"], unique=False
        )
        op.create_index(
            op.f("ix_donation_is_verified"), "donation", ["is_verified"], unique=False
        )
        op.create_index(
            op.f("ix_donation_need_id"), "donation", ["need_id"], unique=False
        )
        op.create_index(
            op.f("ix_donation_pending_receipt_token_hash"),
            "donation",
            ["pending_receipt_token_hash"],
            unique=False,
        )
        op.create_index(
            op.f("ix_donation_status"), "donation", ["status"], unique=False
        )
    if not inspector.has_table("volunteermatch"):
        op.create_table(
            "volunteermatch",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("need_id", sa.Integer(), nullable=False),
            sa.Column("volunteer_id", sa.Integer(), nullable=False),
            sa.Column(
                "matched_by_admin", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("assigned_for", sa.DateTime(), nullable=True),
            sa.Column("matched_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["need_id"],
                ["beneficiaryneed.id"],
            ),
            sa.ForeignKeyConstraint(
                ["volunteer_id"],
                ["volunteer.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_volunteermatch_assigned_for"),
            "volunteermatch",
            ["assigned_for"],
            unique=False,
        )
        op.create_index(
            op.f("ix_volunteermatch_need_id"),
            "volunteermatch",
            ["need_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_volunteermatch_volunteer_id"),
            "volunteermatch",
            ["volunteer_id"],
            unique=False,
        )
    if not inspector.has_table("volunteeroffer"):
        op.create_table(
            "volunteeroffer",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("need_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column(
                "volunteer_skill", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "status", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["need_id"],
                ["beneficiaryneed.id"],
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["user.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_volunteeroffer_need_id"),
            "volunteeroffer",
            ["need_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_volunteeroffer_status"), "volunteeroffer", ["status"], unique=False
        )
        op.create_index(
            op.f("ix_volunteeroffer_user_id"),
            "volunteeroffer",
            ["user_id"],
            unique=False,
        )
    if not inspector.has_table("donationallocation"):
        op.create_table(
            "donationallocation",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("donation_id", sa.Integer(), nullable=False),
            sa.Column("need_id", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["donation_id"],
                ["donation.id"],
            ),
            sa.ForeignKeyConstraint(
                ["need_id"],
                ["beneficiaryneed.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "donation_id", "need_id", name="uq_donationallocation_donation_need"
            ),
        )
        op.create_index(
            op.f("ix_donationallocation_donation_id"),
            "donationallocation",
            ["donation_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_donationallocation_need_id"),
            "donationallocation",
            ["need_id"],
            unique=False,
        )
    if not inspector.has_table("receiptaccess"):
        op.create_table(
            "receiptaccess",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("donation_id", sa.Integer(), nullable=False),
            sa.Column(
                "token_hash",
                sqlmodel.sql.sqltypes.AutoString(length=255),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["donation_id"],
                ["donation.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_receiptaccess_donation_id"),
            "receiptaccess",
            ["donation_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_receiptaccess_expires_at"),
            "receiptaccess",
            ["expires_at"],
            unique=False,
        )
        op.create_index(
            op.f("ix_receiptaccess_token_hash"),
            "receiptaccess",
            ["token_hash"],
            unique=True,
        )


def downgrade() -> None:
    raise RuntimeError(
        "The baseline may include pre-existing tables; restore a backup or add a forward migration."
    )
