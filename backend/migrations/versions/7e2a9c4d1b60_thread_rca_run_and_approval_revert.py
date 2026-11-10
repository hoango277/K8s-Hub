"""chat_threads.rca_run_id; approvals.before_state, approvals.reverts_id

- A conversation can be opened from a diagnosis ("Ask in chat"): the thread
  remembers which run it is about, so every turn tells the assistant
  (docs/ke-hoach/noi-rca-chat-skills.md).
- An executed change records the objects as they were just before it ran, so
  it can be reverted later by a reverse proposal; the reverse proposal points
  back at the change it undoes (docs/ke-hoach/hoan-tac-thay-doi.md).

Revision ID: 7e2a9c4d1b60
Revises: c3d9e1a7f402
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '7e2a9c4d1b60'
down_revision = 'c3d9e1a7f402'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('chat_threads', sa.Column('rca_run_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        op.f('fk_chat_threads_rca_run_id_rca_runs'), 'chat_threads', 'rca_runs',
        ['rca_run_id'], ['id'], ondelete='SET NULL',
    )
    op.add_column('approvals', sa.Column('before_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('approvals', sa.Column('reverts_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        op.f('fk_approvals_reverts_id_approvals'), 'approvals', 'approvals',
        ['reverts_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(op.f('ix_approvals_reverts_id'), 'approvals', ['reverts_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_approvals_reverts_id'), table_name='approvals')
    op.drop_constraint(op.f('fk_approvals_reverts_id_approvals'), 'approvals', type_='foreignkey')
    op.drop_column('approvals', 'reverts_id')
    op.drop_column('approvals', 'before_state')
    op.drop_constraint(op.f('fk_chat_threads_rca_run_id_rca_runs'), 'chat_threads', type_='foreignkey')
    op.drop_column('chat_threads', 'rca_run_id')
