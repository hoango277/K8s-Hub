"""add login: new roles, password, refresh token

Revision ID: 3b38688cb212
Revises: cd18dce5b7cb

Three things:
  1. Rename roles viewer/operator/admin -> user/engineer/admin (data is changed
     BEFORE the CHECK constraint, otherwise existing rows violate the constraint).
  2. Add password_hash + last_login_at to users.
  3. A refresh_tokens table for revocable login sessions.
"""
from alembic import op
import sqlalchemy as sa


revision = '3b38688cb212'
down_revision = 'cd18dce5b7cb'
branch_labels = None
depends_on = None

_ROLE_UPGRADE_MAP = {"operator": "engineer", "viewer": "user"}
_ROLE_DOWNGRADE_MAP = {v: k for k, v in _ROLE_UPGRADE_MAP.items()}


def upgrade() -> None:
    users = sa.table("users", sa.column("role", sa.String))

    # --- 1a. Migrate existing data BEFORE changing the constraint ---
    for old, new in _ROLE_UPGRADE_MAP.items():
        op.execute(users.update().where(users.c.role == old).values(role=new))

    # --- 1b. Replace the CHECK constraint (name kept as-is) ---
    op.drop_constraint("role_hop_le", "users", type_="check")
    op.create_check_constraint(
        "role_hop_le", "users", "role IN ('admin', 'engineer', 'user')"
    )

    # --- 1c. Change the role column default: operator -> user ---
    op.alter_column("users", "role", server_default="user")

    # --- 2. New columns for login ---
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True)
    )

    # --- 3. Revocable login sessions ---
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_column("users", "last_login_at")
    op.drop_column("users", "password_hash")

    op.alter_column("users", "role", server_default="operator")
    op.drop_constraint("role_hop_le", "users", type_="check")
    op.create_check_constraint(
        "role_hop_le", "users", "role IN ('viewer', 'operator', 'admin')"
    )

    users = sa.table("users", sa.column("role", sa.String))
    for new, old in _ROLE_DOWNGRADE_MAP.items():
        op.execute(users.update().where(users.c.role == new).values(role=old))
