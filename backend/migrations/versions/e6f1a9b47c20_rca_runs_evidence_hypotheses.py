"""Create the RCA run, evidence, and hypothesis tables.

Revision ID: e6f1a9b47c20
Revises: df3c82e3549e
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e6f1a9b47c20"
down_revision = "df3c82e3549e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rca_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("target_kind", sa.String(length=40), nullable=False),
        sa.Column("target_name", sa.String(length=253), nullable=False),
        sa.Column("namespace", sa.String(length=253), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_rca_runs_status_hop_le"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rca_runs")),
    )
    op.create_index(op.f("ix_rca_runs_started_at"), "rca_runs", ["started_at"])

    op.create_table(
        "rca_evidence",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["rca_runs.id"],
            name=op.f("fk_rca_evidence_run_id_rca_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rca_evidence")),
    )
    op.create_index(op.f("ix_rca_evidence_run_id"), "rca_evidence", ["run_id"])

    op.create_table(
        "rca_hypotheses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("rank > 0", name=op.f("ck_rca_hypotheses_rank_duong")),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_rca_hypotheses_confidence_hop_le"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["rca_runs.id"],
            name=op.f("fk_rca_hypotheses_run_id_rca_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rca_hypotheses")),
        sa.UniqueConstraint("run_id", "rank", name="uq_rca_hypotheses_run_rank"),
    )
    op.create_index(op.f("ix_rca_hypotheses_run_id"), "rca_hypotheses", ["run_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_rca_hypotheses_run_id"), table_name="rca_hypotheses")
    op.drop_table("rca_hypotheses")
    op.drop_index(op.f("ix_rca_evidence_run_id"), table_name="rca_evidence")
    op.drop_table("rca_evidence")
    op.drop_index(op.f("ix_rca_runs_started_at"), table_name="rca_runs")
    op.drop_table("rca_runs")
