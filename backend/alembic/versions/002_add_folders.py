"""
添加 folders 表 + coursewares/homeworks 的 folder_id 外键

Revision ID: 002
Revises: 001
Create Date: 2026-06-28
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. 创建 folders 表 ─────────────────────
    op.create_table(
        "folders",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(16), nullable=False,
                  comment="courseware | homework"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_check_constraint(
        "ck_folder_category_valid",
        "folders",
        "category IN ('courseware', 'homework')",
    )
    op.create_index("ix_folders_category", "folders", ["category"])

    # ── 2. 给 coursewares 添加 folder_id ───────
    op.add_column(
        "coursewares",
        sa.Column("folder_id", UUID(as_uuid=False),
                  sa.ForeignKey("folders.id", ondelete="SET NULL"),
                  nullable=True),
    )

    # ── 3. 给 homeworks 添加 folder_id ─────────
    op.add_column(
        "homeworks",
        sa.Column("folder_id", UUID(as_uuid=False),
                  sa.ForeignKey("folders.id", ondelete="SET NULL"),
                  nullable=True),
    )


def downgrade() -> None:
    op.drop_column("homeworks", "folder_id")
    op.drop_column("coursewares", "folder_id")
    op.drop_index("ix_folders_category", table_name="folders")
    op.drop_table("folders")
