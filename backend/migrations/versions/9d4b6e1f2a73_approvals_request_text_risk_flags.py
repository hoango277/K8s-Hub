"""approvals.request_text, approvals.risk_flags: where a proposal came from

The user's question in the turn that produced the proposal, and the tool
outputs of that turn flagged as possible prompt injection. Both nullable:
older rows and proposals made outside a chat turn have neither.

Follows c5a19f3e7b22. When written, the history had a second head
(e6f1a9b47c20, the first RCA tables); that migration was later replaced by
b81f0c2d4e57, which follows this one, so the chain is linear again.

Revision ID: 9d4b6e1f2a73
Revises: c5a19f3e7b22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '9d4b6e1f2a73'
down_revision = 'c5a19f3e7b22'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('approvals', sa.Column('request_text', sa.Text(), nullable=True))
    op.add_column(
        'approvals',
        sa.Column('risk_flags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('approvals', 'risk_flags')
    op.drop_column('approvals', 'request_text')
