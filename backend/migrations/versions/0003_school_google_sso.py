"""schools: voeg Google Workspace SSO credentials toe per school

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-03

Elke school heeft zijn eigen Google Workspace omgeving en dus
zijn eigen OAuth2 client_id en client_secret. Deze worden per school
opgeslagen en nooit blootgesteld via de API (enkel of ze ingesteld zijn).
"""
from alembic import op
import sqlalchemy as sa

revision      = '0003'
down_revision = '0002'
branch_labels = None
depends_on    = None


def upgrade():
    op.add_column('schools',
        sa.Column('google_client_id', sa.String(255), nullable=True))
    op.add_column('schools',
        sa.Column('google_client_secret', sa.String(255), nullable=True))


def downgrade():
    op.drop_column('schools', 'google_client_secret')
    op.drop_column('schools', 'google_client_id')
