"""settings overrides and change history

Two tables for the Settings page:
  - settings_overrides: values changed on the web, so they survive a restart
  - settings_changes:   append-only history of who changed what, and when

Autogenerate also proposed dropping the server default of `users.role`; that
drift is unrelated to this change and was removed from the migration on purpose.

Revision ID: f0e04ca322b1
Revises: 3b38688cb212
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'f0e04ca322b1'
down_revision = '3b38688cb212'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'settings_changes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=True),
        sa.Column('actor_email', sa.String(length=320), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('field', sa.String(length=64), nullable=True),
        sa.Column('old_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('new_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('secret', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ['actor_id'], ['users.id'],
            name=op.f('fk_settings_changes_actor_id_users'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_settings_changes')),
    )
    op.create_index(
        op.f('ix_settings_changes_changed_at'), 'settings_changes', ['changed_at'], unique=False
    )
    op.create_table(
        'settings_overrides',
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('secret', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ['updated_by'], ['users.id'],
            name=op.f('fk_settings_overrides_updated_by_users'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('name', name=op.f('pk_settings_overrides')),
    )


def downgrade() -> None:
    op.drop_table('settings_overrides')
    op.drop_index(op.f('ix_settings_changes_changed_at'), table_name='settings_changes')
    op.drop_table('settings_changes')
