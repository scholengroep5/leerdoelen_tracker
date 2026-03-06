"""assessments: herstructureer naar klasgebonden model

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-05

Wijziging: assessments zijn niet langer gekoppeld aan een individuele
leerkracht (user_id) maar aan een klas (class_id). Meerdere leerkrachten
van dezelfde klas delen één set beoordelingen.

OPGELET: dit dropt de bestaande assessments tabel — testdata gaat verloren.
"""
from alembic import op
import sqlalchemy as sa

revision      = '0004'
down_revision = '0003'
branch_labels = None
depends_on    = None


def upgrade():
    # Drop oude tabel volledig (testomgeving — geen productiedata)
    op.execute("DROP TABLE IF EXISTS assessments CASCADE")

    # Nieuwe tabel: klasgebonden, geen user_id
    op.execute("""
        CREATE TABLE assessments (
            id             SERIAL PRIMARY KEY,
            class_id       INTEGER NOT NULL REFERENCES classes(id)      ON DELETE CASCADE,
            school_year_id INTEGER NOT NULL REFERENCES school_years(id) ON DELETE CASCADE,
            vak_id         VARCHAR(50) NOT NULL,
            goal_id        VARCHAR(50) NOT NULL,
            status         VARCHAR(10) NOT NULL,
            opmerking      VARCHAR(500),
            updated_at     TIMESTAMP DEFAULT NOW(),
            UNIQUE(class_id, school_year_id, vak_id, goal_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_assessments_class_year ON assessments(class_id, school_year_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_assessments_vak ON assessments(vak_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS assessments CASCADE")
    # Zet terug naar user-gebaseerde tabel (zonder data)
    op.execute("""
        CREATE TABLE assessments (
            id             SERIAL PRIMARY KEY,
            user_id        INTEGER NOT NULL REFERENCES users(id)        ON DELETE CASCADE,
            school_id      INTEGER NOT NULL REFERENCES schools(id)      ON DELETE CASCADE,
            school_year_id INTEGER NOT NULL REFERENCES school_years(id) ON DELETE CASCADE,
            vak_id         VARCHAR(50) NOT NULL,
            goal_id        VARCHAR(50) NOT NULL,
            status         VARCHAR(10) NOT NULL,
            opmerking      VARCHAR(500),
            updated_at     TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, school_year_id, vak_id, goal_id)
        )
    """)