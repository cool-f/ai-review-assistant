"""add original_text to coursewares

Revision ID: 003
Revises: 002
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'coursewares',
        sa.Column('original_text', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('coursewares', 'original_text')
