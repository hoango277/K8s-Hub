"""rca_hypotheses.feedback*, rca_weights: learning rule weights from feedback

Engineers (and the evaluation's ground truth) mark a ranked cause as right or
wrong; rca_weights counts that per rule and per event type
(app/modules/rca/learning.py).

Revision ID: c3d9e1a7f402
Revises: b81f0c2d4e57
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d9e1a7f402'
down_revision = 'b81f0c2d4e57'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('rca_hypotheses', sa.Column('feedback', sa.String(length=16), nullable=True))
    op.add_column('rca_hypotheses', sa.Column('feedback_by_email', sa.String(length=320), nullable=True))
    op.add_column('rca_hypotheses', sa.Column('feedback_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'rca_weights',
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('positive', sa.Integer(), nullable=False),
        sa.Column('negative', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key', name=op.f('pk_rca_weights')),
    )


def downgrade() -> None:
    op.drop_table('rca_weights')
    op.drop_column('rca_hypotheses', 'feedback_at')
    op.drop_column('rca_hypotheses', 'feedback_by_email')
    op.drop_column('rca_hypotheses', 'feedback')
