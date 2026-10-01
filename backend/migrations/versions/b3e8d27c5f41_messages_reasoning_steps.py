"""messages.reasoning_steps: reasoning split around tool calls

Lets the chat show thought → tool → thought in order after a reload.

Revision ID: b3e8d27c5f41
Revises: a7c41e9b2d10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b3e8d27c5f41'
down_revision = 'a7c41e9b2d10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('reasoning_steps', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'reasoning_steps')
