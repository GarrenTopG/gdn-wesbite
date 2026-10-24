"""Add image and article content to community needs.

Revision ID: 9f89a4e2cc71
Revises: 8c41d62a9f30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9f89a4e2cc71"
down_revision: Union[str, None] = "8c41d62a9f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("beneficiaryneed")
    }
    missing_columns = {"article", "image_url", "image_alt"} - columns
    if missing_columns:
        with op.batch_alter_table("beneficiaryneed") as batch_op:
            if "article" in missing_columns:
                batch_op.add_column(sa.Column("article", sa.Text(), nullable=True))
            if "image_url" in missing_columns:
                batch_op.add_column(
                    sa.Column("image_url", sa.String(length=2048), nullable=True)
                )
            if "image_alt" in missing_columns:
                batch_op.add_column(
                    sa.Column("image_alt", sa.String(length=500), nullable=True)
                )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("beneficiaryneed")
    }
    existing_columns = {"article", "image_url", "image_alt"} & columns
    if existing_columns:
        with op.batch_alter_table("beneficiaryneed") as batch_op:
            for column in ("image_alt", "image_url", "article"):
                if column in existing_columns:
                    batch_op.drop_column(column)
