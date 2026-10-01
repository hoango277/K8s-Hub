"""mcp_servers, mcp_tools: external MCP servers again, with a per-tool policy

Engineers/admins connect MCP servers; each reported tool has `enabled` and
`requires_approval` (defaults: off, and approval required).

Revision ID: c5a19f3e7b22
Revises: b3e8d27c5f41
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c5a19f3e7b22'
down_revision = 'b3e8d27c5f41'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('mcp_servers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('token_enc', sa.Text(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('refreshed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_mcp_servers_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mcp_servers')),
    sa.UniqueConstraint('name', name=op.f('uq_mcp_servers_name'))
    )
    op.create_table('mcp_tools',
    sa.Column('server_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('input_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('read_only_hint', sa.Boolean(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('requires_approval', sa.Boolean(), nullable=False),
    sa.Column('policy_updated_by', sa.UUID(), nullable=True),
    sa.Column('policy_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['policy_updated_by'], ['users.id'], name=op.f('fk_mcp_tools_policy_updated_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['server_id'], ['mcp_servers.id'], name=op.f('fk_mcp_tools_server_id_mcp_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('server_id', 'name', name=op.f('pk_mcp_tools'))
    )


def downgrade() -> None:
    op.drop_table('mcp_tools')
    op.drop_table('mcp_servers')
