"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Alle tabellen aanmaken als ze nog niet bestaan
    # (idempotent via checkfirst=True)
    op.execute("""
        CREATE TABLE IF NOT EXISTS schools (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(100) NOT NULL UNIQUE,
            email_domains TEXT[] NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS school_years (
            id SERIAL PRIMARY KEY,
            school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
            label VARCHAR(20) NOT NULL UNIQUE,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255),
            first_name VARCHAR(100),
            last_name VARCHAR(100),
            role VARCHAR(20) NOT NULL DEFAULT 'teacher',
            school_id INTEGER REFERENCES schools(id) ON DELETE SET NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            last_login TIMESTAMP,
            oauth_provider VARCHAR(20),
            oauth_id VARCHAR(255),
            entra_tenant_id VARCHAR(255)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS classes (
            id SERIAL PRIMARY KEY,
            school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
            name VARCHAR(50) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(school_id, name)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS teacher_classes (
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            class_id INTEGER REFERENCES classes(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, class_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS assessments (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
            school_year_id INTEGER NOT NULL REFERENCES school_years(id) ON DELETE CASCADE,
            vak_id VARCHAR(50) NOT NULL,
            goal_id VARCHAR(50) NOT NULL,
            status VARCHAR(10) NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, school_year_id, vak_id, goal_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            school_id INTEGER REFERENCES schools(id) ON DELETE SET NULL,
            action VARCHAR(50) NOT NULL,
            category VARCHAR(20) NOT NULL,
            target_type VARCHAR(50),
            target_id VARCHAR(100),
            detail TEXT,
            ip_address VARCHAR(45)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_timestamp ON audit_logs(timestamp)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs(action)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_category ON audit_logs(category)")

    # Verwijder school_year_id van classes als die nog bestaat (oude structuur)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='classes' AND column_name='school_year_id'
            ) THEN
                ALTER TABLE classes DROP COLUMN school_year_id;
            END IF;
        END $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS assessments CASCADE")
    op.execute("DROP TABLE IF EXISTS teacher_classes CASCADE")
    op.execute("DROP TABLE IF EXISTS classes CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
    op.execute("DROP TABLE IF EXISTS school_years CASCADE")
    op.execute("DROP TABLE IF EXISTS schools CASCADE")
