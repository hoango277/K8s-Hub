"""approvals, custom CLI tools; drop external MCP servers

  - approvals: cluster changes proposed by the assistant — request, dry-run,
    diff, decision, result and verification in one audited row;
  - tool_calls.approval_id: the chat shows the approval card of a call;
  - custom_tools: CLIs wrapped as tools on the web (kubectl-ai style);
  - mcp_servers, mcp_tools and tool_settings.danger removed: every tool now
    lives in the backend (decision of 30/09/2026).

Revision ID: a7c41e9b2d10
Revises: df3c82e3549e
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a7c41e9b2d10'
down_revision = 'df3c82e3549e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('approvals',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('namespace', sa.String(length=63), nullable=True),
    sa.Column('target', sa.String(length=300), nullable=True),
    sa.Column('danger', sa.String(length=16), nullable=False),
    sa.Column('source', sa.String(length=64), nullable=False),
    sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('diff', sa.Text(), nullable=True),
    sa.Column('dry_run_output', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('result', sa.Text(), nullable=True),
    sa.Column('verify_ok', sa.Boolean(), nullable=True),
    sa.Column('verify_message', sa.Text(), nullable=True),
    sa.Column('requested_by', sa.UUID(), nullable=True),
    sa.Column('requested_by_email', sa.String(length=320), nullable=False),
    sa.Column('decided_by', sa.UUID(), nullable=True),
    sa.Column('decided_by_email', sa.String(length=320), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('thread_id', sa.UUID(), nullable=True),
    sa.Column('tool_call_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("danger IN ('caution', 'dangerous')", name=op.f('ck_approvals_danger')),
    sa.CheckConstraint("status IN ('pending', 'executing', 'executed', 'failed', 'rejected', 'expired')", name=op.f('ck_approvals_status')),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], name=op.f('fk_approvals_decided_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_approvals_requested_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['thread_id'], ['chat_threads.id'], name=op.f('fk_approvals_thread_id_chat_threads'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals'))
    )
    op.create_index(op.f('ix_approvals_created_at'), 'approvals', ['created_at'], unique=False)
    op.create_index(op.f('ix_approvals_namespace'), 'approvals', ['namespace'], unique=False)
    op.create_index(op.f('ix_approvals_status'), 'approvals', ['status'], unique=False)

    op.add_column('tool_calls', sa.Column('approval_id', sa.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_tool_calls_approval_id_approvals'), 'tool_calls', 'approvals', ['approval_id'], ['id'], ondelete='SET NULL')

    op.create_table('custom_tools',
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('command', sa.String(length=64), nullable=False),
    sa.Column('usage', sa.Text(), nullable=False),
    sa.Column('read_only_prefixes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('timeout_seconds', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_custom_tools_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('name', name=op.f('pk_custom_tools'))
    )

    op.drop_table('mcp_tools')
    op.drop_table('mcp_servers')
    op.drop_column('tool_settings', 'danger')


def downgrade() -> None:
    op.add_column('tool_settings', sa.Column('danger', sa.String(length=16), nullable=True))
    op.create_table('mcp_servers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('token_enc', sa.Text(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('refreshed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mcp_servers')),
    sa.UniqueConstraint('name', name=op.f('uq_mcp_servers_name'))
    )
    op.create_table('mcp_tools',
    sa.Column('server_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('input_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('read_only_hint', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['server_id'], ['mcp_servers.id'], name=op.f('fk_mcp_tools_server_id_mcp_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('server_id', 'name', name=op.f('pk_mcp_tools'))
    )
    op.drop_table('custom_tools')
    op.drop_constraint(op.f('fk_tool_calls_approval_id_approvals'), 'tool_calls', type_='foreignkey')
    op.drop_column('tool_calls', 'approval_id')
    op.drop_index(op.f('ix_approvals_status'), table_name='approvals')
    op.drop_index(op.f('ix_approvals_namespace'), table_name='approvals')
    op.drop_index(op.f('ix_approvals_created_at'), table_name='approvals')
    op.drop_table('approvals')
