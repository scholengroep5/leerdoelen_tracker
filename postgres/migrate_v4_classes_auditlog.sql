-- ══════════════════════════════════════════════════════════════════════════════
-- MIGRATIE v4: Klassen zonder school_year_id + Auditlog tabel
-- Uitvoeren op bestaande installaties:
--   docker exec -i leerdoelen_db psql -U leerdoelen leerdoelen < postgres/migrate_v4_classes_auditlog.sql
-- ══════════════════════════════════════════════════════════════════════════════

BEGIN;

-- 1. Verwijder school_year_id van classes (klassen zijn nu schooljaar-onafhankelijk)
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='classes' AND column_name='school_year_id'
    ) THEN
        ALTER TABLE classes DROP CONSTRAINT IF EXISTS classes_school_year_id_fkey;
        ALTER TABLE classes DROP COLUMN school_year_id;
        RAISE NOTICE 'school_year_id verwijderd van classes';
    ELSE
        RAISE NOTICE 'school_year_id bestond al niet — niets te doen';
    END IF;
END $$;

-- 2. Unieke constraint op (school_id, name) voor klassen
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_class_school_name'
    ) THEN
        ALTER TABLE classes ADD CONSTRAINT uq_class_school_name UNIQUE (school_id, name);
        RAISE NOTICE 'Unique constraint uq_class_school_name toegevoegd';
    END IF;
END $$;

-- 3. Auditlog tabel aanmaken
CREATE TABLE IF NOT EXISTS audit_logs (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMP NOT NULL DEFAULT NOW(),
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    school_id   INTEGER REFERENCES schools(id) ON DELETE SET NULL,
    action      VARCHAR(50) NOT NULL,
    category    VARCHAR(20) NOT NULL,
    target_type VARCHAR(50),
    target_id   VARCHAR(100),
    detail      TEXT,
    ip_address  VARCHAR(45)
);

CREATE INDEX IF NOT EXISTS ix_audit_logs_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action    ON audit_logs(action);
CREATE INDEX IF NOT EXISTS ix_audit_logs_category  ON audit_logs(category);

COMMIT;

-- Controleer resultaat
SELECT 'classes kolommen:' AS info;
SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'classes' ORDER BY ordinal_position;

SELECT 'audit_logs tabel:' AS info;
SELECT COUNT(*) AS entries FROM audit_logs;
