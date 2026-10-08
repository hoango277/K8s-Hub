"""rca_runs, rca_hypotheses: the Groot-style RCA (app/modules/rca)

Replaces the earlier RCA tables (e6f1a9b47c20, deleted 07/10/2026 before any
database ran it). Follows 9d4b6e1f2a73, so the history has a single head again.

Revision ID: b81f0c2d4e57
Revises: 9d4b6e1f2a73
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b81f0c2d4e57'
down_revision = '9d4b6e1f2a73'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'rca_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('trig', sa.String(length=16), nullable=False),
        sa.Column('requested_by', sa.UUID(), nullable=True),
        sa.Column('requested_by_email', sa.String(length=320), nullable=False),
        sa.Column('namespace', sa.String(length=63), nullable=False),
        sa.Column('target_kind', sa.String(length=32), nullable=True),
        sa.Column('target_name', sa.String(length=253), nullable=True),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('graph', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('report_status', sa.String(length=16), nullable=False),
        sa.Column('report', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('llm_trace_id', sa.String(length=32), nullable=True),
        sa.Column('approval_id', sa.UUID(), nullable=True),
        sa.Column('alert_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("trig IN ('manual', 'chat', 'alert', 'scan')", name=op.f('ck_rca_runs_trigger')),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name=op.f('ck_rca_runs_status')),
        sa.CheckConstraint("report_status IN ('none', 'running', 'done', 'failed')", name=op.f('ck_rca_runs_report_status')),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_rca_runs_requested_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approval_id'], ['approvals.id'], name=op.f('fk_rca_runs_approval_id_approvals'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rca_runs')),
    )
    op.create_index(op.f('ix_rca_runs_namespace'), 'rca_runs', ['namespace'], unique=False)
    op.create_index(op.f('ix_rca_runs_status'), 'rca_runs', ['status'], unique=False)
    op.create_index(op.f('ix_rca_runs_created_at'), 'rca_runs', ['created_at'], unique=False)
    op.create_index(op.f('ix_rca_runs_alert_fingerprint'), 'rca_runs', ['alert_fingerprint'], unique=False)

    op.create_table(
        'rca_hypotheses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(length=400), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('chain', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('rules', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('verdict', sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['rca_runs.id'], name=op.f('fk_rca_hypotheses_run_id_rca_runs'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rca_hypotheses')),
        sa.UniqueConstraint('run_id', 'rank', name='uq_rca_hypotheses_run_rank'),
    )
    op.create_index(op.f('ix_rca_hypotheses_run_id'), 'rca_hypotheses', ['run_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_rca_hypotheses_run_id'), table_name='rca_hypotheses')
    op.drop_table('rca_hypotheses')
    op.drop_index(op.f('ix_rca_runs_alert_fingerprint'), table_name='rca_runs')
    op.drop_index(op.f('ix_rca_runs_created_at'), table_name='rca_runs')
    op.drop_index(op.f('ix_rca_runs_status'), table_name='rca_runs')
    op.drop_index(op.f('ix_rca_runs_namespace'), table_name='rca_runs')
    op.drop_table('rca_runs')
