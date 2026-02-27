-- ══════════════════════════════════════════════════════════════════════════════
-- MIGRATIE v3: Globale schooljaren
-- Uitvoeren op bestaande installaties die al draaien.
-- Commando: docker exec -i leerdoelen_db psql -U leerdoelen leerdoelen < migrate_v3_global_years.sql
-- ══════════════════════════════════════════════════════════════════════════════

BEGIN;

-- 1. school_id nullable maken (was NOT NULL)
ALTER TABLE school_years ALTER COLUMN school_id DROP NOT NULL;

-- 2. Unieke constraint op label (elk schooljaar bestaat maar één keer)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'school_years_label_key'
    ) THEN
        ALTER TABLE school_years ADD CONSTRAINT school_years_label_key UNIQUE (label);
    END IF;
END $$;

-- 3. Bestaande per-school jaren omzetten naar globale jaren
--    (dubbele labels samenvoegen: bewaar het actieve, verwijder de rest)
DELETE FROM school_years sy1
USING school_years sy2
WHERE sy1.label = sy2.label
  AND sy1.id > sy2.id;

UPDATE school_years SET school_id = NULL;

COMMIT;

-- Controleer resultaat:
SELECT id, label, is_active, school_id FROM school_years ORDER BY label DESC;
