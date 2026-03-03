"""assessment: voeg opmerking kolom toe

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-02
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('assessments',
        sa.Column('opmerking', sa.String(500), nullable=True)
    )


def downgrade():
    op.drop_column('assessments', 'opmerking')
