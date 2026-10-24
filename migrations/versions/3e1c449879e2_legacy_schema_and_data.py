"""Bring pre-migration databases up to the current schema.

Revision ID: 3e1c449879e2
Revises: 6041068d476c
"""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "3e1c449879e2"
down_revision: Union[str, None] = "6041068d476c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_COMMUNITY_STORIES = (
    {
        "slug": "another-big-win-for-our-youth-financial-literacy-employment-milestones",
        "title": "A Big Win for Our Youth: Financial Literacy and New Job Offers",
        "category": "Impact Update",
        "image_url": "/static/images/news/financial-literacy.png",
        "summary": "Aurorah's second youth group completed its introductory financial "
        "literacy programme, while three participants received full-time job "
        "offers.",
        "content": "Aurorah's second group of youth in the National Youth Service Program "
        "has completed its introductory Financial Literacy Program. Many of the "
        "participants have also been volunteering at early childhood development "
        "centres, giving their time and skills back to the community.\n"
        "\n"
        "Three of the young people have received full-time job offers. Their "
        "achievement is a reminder that youth development is about more than "
        "keeping young people busy: it is about creating opportunities, building "
        "confidence, developing skills and opening doors to employment.\n"
        "\n"
        "We are proud of these young people and of everyone who continues to show "
        "up, volunteer and learn. Thank you to the contributors and facilitators "
        "helping equip young people with skills for life.\n"
        "\n"
        "The group has completed the introductory programme and is looking "
        "forward to advanced financial literacy training.",
        "is_featured": True,
    },
    {
        "slug": "aurorah-youth-community-clean-up",
        "title": "More Than a Clean-Up: Young People Take Responsibility",
        "category": "Community Outreaches",
        "image_url": "/static/images/news/mandela-day-and-youth-clean-up.png",
        "summary": "Aurorah youth came together for a community clean-up and reflected on "
        "shared responsibility, Ubuntu and caring for the place they call home.",
        "content": "Aurorah youth took to the streets for a community clean-up—not because "
        "everything can be fixed in a day, but because change starts when people "
        "are willing to take responsibility.\n"
        "\n"
        "Afterwards, the young people reflected on feeling proud, giving back, "
        "working together and putting Ubuntu into practice. One reflection stood "
        "out: “We shouldn't just complain about our community—we must also be "
        "willing to do something about it.”\n"
        "\n"
        "A cleaner community starts with us. A stronger community starts with us. "
        "Ubuntu starts with us.",
        "is_featured": False,
    },
    {
        "slug": "four-years-aurorah-community-hotspot-library-mandela-day",
        "title": "Celebrating Mandela Day and Four Years of the Community Hotspot Library",
        "category": "Community Outreaches",
        "image_url": "/static/images/news/mandela-day-and-youth-clean-up.png",
        "summary": "Aurorah marked Mandela Day and four years of its Community Hotspot "
        "Library with a day of service, learning and connection.",
        "content": "Mandela Day was an opportunity to celebrate four years of Aurorah's "
        "Community Hotspot Library and a day of service with the community.\n"
        "\n"
        "With support from donors, partners and community members, senior-group "
        "members received winter items including blankets, hoodies, caps and "
        "scarves. Younger children received caps and took part in a day of fun, "
        "connection and learning.\n"
        "\n"
        "Fifty Aurorah youth participated, engaging with children, facilitating "
        "indigenous games and putting Ubuntu into practice. The day ended with a "
        "shared meal.\n"
        "\n"
        "The library began with a vision of giving children and young people a "
        "place to learn, grow and belong. Four years on, Aurorah remains "
        "committed to building that space with the community. Thank you to every "
        "donor, partner, volunteer, neighbour and community member who has "
        "contributed to the journey.",
        "is_featured": False,
    },
    {
        "slug": "serving-hope-and-warmth-community-cook-off-supports-over-400-residents",
        "title": "A Community Cook-Off Brings Food and Warmth to Around 400 People",
        "category": "Community Outreaches",
        "image_url": "/static/images/news/community-cook-off.png",
        "summary": "Aurorah's winter cook-off served around 400 people, with youth and "
        "volunteers giving their time to support neighbours.",
        "content": "Aurorah's community cook-off served around 400 people. The day was about "
        "more than numbers: it was also about young people and volunteers showing "
        "up with pride, care and a sense of family.\n"
        "\n"
        "Winter can be especially difficult for households facing choices between "
        "food, electricity and keeping warm. Aurorah shared its intention to "
        "continue serving through winter and invited people to donate warm items "
        "such as blankets, socks, beanies and jackets.\n"
        "\n"
        "The update also announced a planned meal for senior mothers on 12 May. "
        "Thank you to everyone who contributed and to the team and youth who gave "
        "their time to serve.",
        "is_featured": False,
    },
    {
        "slug": "a-win-worth-celebrating-3-more-youth-secure-full-time-contracts",
        "title": "A Win Worth Celebrating: Three More Youth Secure Full-Time Contracts",
        "category": "Impact Update",
        "image_url": "/static/images/news/youth-employment.png",
        "summary": "Three more young people secured one-year full-time contracts in "
        "Aurorah's youth programme, bringing the number who had moved forward to "
        "eight.",
        "content": "Aurorah is celebrating three more young people who secured one-year "
        "full-time contracts.\n"
        "\n"
        "The programme began with 50 young people on 15 July. With these "
        "contracts, eight had moved forward into employment opportunities, while "
        "42 remained on the journey. The update celebrated each step and "
        "encouraged the young people still participating to keep showing up, "
        "learning and growing.\n"
        "\n"
        "Congratulations to the three young people. Their progress shows what can "
        "happen when young people are given opportunities, support and a chance "
        "to believe in themselves.",
        "is_featured": False,
    },
)


def _add_column_if_missing(table: str, column: sa.Column) -> bool:
    inspector = sa.inspect(op.get_bind())
    if column.name in {item["name"] for item in inspector.get_columns(table)}:
        return False
    op.add_column(table, column)
    return True


def _create_index_if_missing(
    table: str, name: str, columns: list[str], *, unique: bool = False
) -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes(table)}
    if name not in existing_indexes:
        op.create_index(name, table, columns, unique=unique)


def _normalize_user_roles(connection: sa.Connection) -> None:
    role_lookup = {
        "administrator": "ADMINISTRATOR",
        "admin": "ADMINISTRATOR",
        "case_worker": "CASE_WORKER",
        "finance": "FINANCE",
        "content_editor": "CONTENT_EDITOR",
        "read_only": "READ_ONLY",
        "user": "USER",
        "volunteer": "USER",
    }
    updates = []
    for user_id, current_role in connection.execute(
        sa.text("SELECT id, role FROM [user]")
    ):
        key = current_role.strip().casefold() if isinstance(current_role, str) else ""
        normalized = role_lookup.get(key, "USER")
        if current_role != normalized:
            updates.append({"user_id": user_id, "role": normalized})
    if updates:
        connection.execute(
            sa.text("UPDATE [user] SET role = :role WHERE id = :user_id"),
            updates,
        )


def _normalize_volunteer_available_days(connection: sa.Connection) -> None:
    invalid_ids = []
    for volunteer_id, available_days in connection.execute(
        sa.text(
            "SELECT id, available_days FROM volunteer WHERE available_days IS NOT NULL"
        )
    ):
        try:
            parsed_days = json.loads(available_days)
        except (json.JSONDecodeError, TypeError):
            invalid_ids.append(volunteer_id)
            continue
        if not isinstance(parsed_days, list) or any(
            not isinstance(day, str) for day in parsed_days
        ):
            invalid_ids.append(volunteer_id)
    if invalid_ids:
        connection.execute(
            sa.text("UPDATE volunteer SET available_days = '[]' WHERE id = :id"),
            [{"id": volunteer_id} for volunteer_id in invalid_ids],
        )


def _normalize_volunteer_status(connection: sa.Connection) -> None:
    status_lookup = {
        "active": "ACTIVE",
        "inactive": "INACTIVE",
        "assigned": "ASSIGNED",
    }
    updates = []
    for volunteer_id, current_status in connection.execute(
        sa.text("SELECT id, status FROM volunteer")
    ):
        key = (
            current_status.strip().casefold() if isinstance(current_status, str) else ""
        )
        normalized = status_lookup.get(key, "ACTIVE")
        if current_status != normalized:
            updates.append({"volunteer_id": volunteer_id, "status": normalized})
    if updates:
        connection.execute(
            sa.text("UPDATE volunteer SET status = :status WHERE id = :volunteer_id"),
            updates,
        )


def _seed_community_stories(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            "DELETE FROM newsarticle WHERE slug = "
            "'a-win-worth-celebrating-three-more-youth-full-time-contracts'"
        )
    )
    for story in LEGACY_COMMUNITY_STORIES:
        existing = connection.execute(
            sa.text("SELECT id FROM newsarticle WHERE slug = :slug"),
            {"slug": story["slug"]},
        ).first()
        if existing:
            connection.execute(
                sa.text(
                    "UPDATE newsarticle SET image_url = :image_url WHERE slug = :slug"
                ),
                {"slug": story["slug"], "image_url": story["image_url"]},
            )
            continue
        connection.execute(
            sa.text(
                "INSERT INTO newsarticle "
                "(title, slug, category, summary, content, image_url, author, "
                "is_featured, published_date, status, created_at) "
                "VALUES (:title, :slug, :category, :summary, :content, :image_url, "
                "'Aurorah Team', :is_featured, NULL, 'Published', CURRENT_TIMESTAMP)"
            ),
            story,
        )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    _add_column_if_missing(
        "newsarticle", sa.Column("published_date", sa.Date(), nullable=True)
    )
    _add_column_if_missing(
        "beneficiaryneed", sa.Column("request_details", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "beneficiaryneed", sa.Column("closed_at", sa.DateTime(), nullable=True)
    )
    _add_column_if_missing(
        "beneficiaryneed",
        sa.Column(
            "is_community_need",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    for name, column_type in (
        ("assigned_staff_id", sa.Integer()),
        ("internal_notes", sa.Text()),
        ("follow_up_at", sa.DateTime()),
        ("deadline", sa.DateTime()),
        ("archived_at", sa.DateTime()),
        ("user_id", sa.Integer()),
    ):
        _add_column_if_missing(
            "beneficiaryneed", sa.Column(name, column_type, nullable=True)
        )
    for name, column_type in (
        ("onboarding_status", sa.String(50)),
        ("next_assignment_at", sa.DateTime()),
        ("archived_at", sa.DateTime()),
    ):
        _add_column_if_missing(
            "volunteer",
            sa.Column(
                name,
                column_type,
                nullable=name == "onboarding_status",
                server_default=(
                    sa.text("'Pending'") if name == "onboarding_status" else None
                ),
            ),
        )
    _add_column_if_missing(
        "volunteermatch", sa.Column("assigned_for", sa.DateTime(), nullable=True)
    )
    donation_status_added = _add_column_if_missing(
        "donation",
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'Submitted'"),
        ),
    )
    for name, column_type in (
        ("archived_at", sa.DateTime()),
        ("pending_receipt_token_hash", sa.String(255)),
    ):
        _add_column_if_missing("donation", sa.Column(name, column_type, nullable=True))
    _add_column_if_missing(
        "newsarticle",
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'Published'"),
        ),
    )
    _add_column_if_missing(
        "newsarticle", sa.Column("archived_at", sa.DateTime(), nullable=True)
    )
    for name, column_type in (
        ("mfa_secret", sa.String()),
        ("mfa_last_counter", sa.Integer()),
        ("phone_number", sa.String(50)),
        ("preferences", sa.JSON()),
    ):
        _add_column_if_missing("user", sa.Column(name, column_type, nullable=True))
    _add_column_if_missing(
        "authsession",
        sa.Column(
            "mfa_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _add_column_if_missing(
        "authsession", sa.Column("mfa_setup_secret", sa.String(), nullable=True)
    )

    for table, column in (
        ("beneficiaryneed", "assigned_staff_id"),
        ("beneficiaryneed", "follow_up_at"),
        ("beneficiaryneed", "deadline"),
        ("beneficiaryneed", "archived_at"),
        ("beneficiaryneed", "is_community_need"),
        ("beneficiaryneed", "user_id"),
        ("volunteer", "onboarding_status"),
        ("volunteer", "next_assignment_at"),
        ("volunteer", "archived_at"),
        ("volunteermatch", "assigned_for"),
        ("donation", "status"),
        ("donation", "archived_at"),
        ("donation", "pending_receipt_token_hash"),
        ("newsarticle", "status"),
        ("newsarticle", "archived_at"),
    ):
        _create_index_if_missing(table, f"ix_{table}_{column}", [column])
    _create_index_if_missing(
        "donationallocation",
        "uq_donationallocation_donation_need",
        ["donation_id", "need_id"],
        unique=True,
    )

    connection = op.get_bind()
    if "published_date" in {
        column["name"] for column in sa.inspect(connection).get_columns("newsarticle")
    }:
        published_date = (
            "CAST(created_at AS DATE)" if dialect == "mssql" else "date(created_at)"
        )
        connection.execute(
            sa.text(
                "UPDATE newsarticle SET published_date = "
                f"{published_date} WHERE published_date IS NULL"
            )
        )
    if donation_status_added:
        connection.execute(
            sa.text(
                "UPDATE donation SET status = CASE "
                "WHEN is_verified = 1 AND amount > 0 "
                "AND allocated_amount >= amount THEN 'Allocated' "
                "WHEN is_verified = 1 THEN 'Received/Verified' "
                "ELSE 'Payment Pending' END"
            )
        )
    connection.execute(
        sa.text(
            "INSERT INTO donationallocation "
            "(donation_id, need_id, amount, created_at) "
            "SELECT d.id, d.need_id, d.allocated_amount, CURRENT_TIMESTAMP "
            "FROM donation d "
            "WHERE d.need_id IS NOT NULL AND d.allocated_amount > 0 "
            "AND NOT EXISTS (SELECT 1 FROM donationallocation a "
            "WHERE a.donation_id = d.id AND a.need_id = d.need_id)"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE beneficiaryneed "
            "SET is_community_need = 1, contact_name = '', contact_phone = '', "
            "full_address = '' "
            "WHERE contact_name = 'Admin Internal' "
            "OR full_address = 'Admin Direct Entry'"
        )
    )
    connection.execute(
        sa.text(
            "DELETE FROM newsarticle WHERE slug = "
            "'shifting-mindsets-financial-skills-training-program-with-avo-vision'"
        )
    )
    _normalize_user_roles(connection)
    _normalize_volunteer_available_days(connection)
    _normalize_volunteer_status(connection)
    _seed_community_stories(connection)

    if dialect == "sqlite":
        for table in ("auditlog", "recordhistory"):
            for action in ("update", "delete"):
                trigger = f"{table}_no_{action}"
                connection.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS {trigger} "
                    f"BEFORE {action.upper()} ON {table} BEGIN "
                    "SELECT RAISE(ABORT, 'audit and history rows are immutable'); "
                    "END"
                )
    elif dialect == "mssql":
        trigger_statements = (
            "CREATE OR ALTER TRIGGER auditlog_no_update ON auditlog "
            "INSTEAD OF UPDATE AS BEGIN "
            ";THROW 50000, 'audit log is immutable', 1; END",
            "CREATE OR ALTER TRIGGER auditlog_no_delete ON auditlog "
            "INSTEAD OF DELETE AS BEGIN "
            ";THROW 50000, 'audit log is immutable', 1; END",
            "CREATE OR ALTER TRIGGER recordhistory_no_update ON recordhistory "
            "INSTEAD OF UPDATE AS BEGIN "
            ";THROW 50000, 'record history is immutable', 1; END",
            "CREATE OR ALTER TRIGGER recordhistory_no_delete ON recordhistory "
            "INSTEAD OF DELETE AS BEGIN "
            ";THROW 50000, 'record history is immutable', 1; END",
        )
        for statement in trigger_statements:
            connection.exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError(
        "This data migration is irreversible; restore a backup or add a forward migration."
    )
