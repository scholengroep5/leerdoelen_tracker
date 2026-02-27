-- ================================================
-- LEERDOELEN TRACKER - DATABASE SCHEMA
-- ================================================

-- Scholengroep scholen
CREATE TABLE schools (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) NOT NULL UNIQUE,
    -- Eén of meerdere e-maildomeinen gekoppeld aan deze school
    -- bv. '{"dekrekel.be", "sintjan.gent.be"}'
    email_domains   TEXT[]       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Gebruikers
-- Rollen:
--   superadmin       → ontwikkelaar/beheerder van het platform
--   scholengroep_ict → maakt scholen aan, wijst directeurs en school_ict toe
--   school_ict       → beheert klassen en leerkrachten van één school
--   director         → leest overzicht van zijn school, geen beheer
--   teacher          → vult leerdoelen in
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255),               -- enkel voor superadmin fallback
    first_name      VARCHAR(100),
    last_name       VARCHAR(100),
    role            VARCHAR(20) NOT NULL DEFAULT 'teacher'
                    CHECK (role IN ('superadmin', 'scholengroep_ict', 'school_ict', 'director', 'teacher')),
    school_id       INTEGER REFERENCES schools(id) ON DELETE SET NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    last_login      TIMESTAMP,
    -- Entra / OAuth2
    oauth_provider  VARCHAR(20),               -- 'microsoft' | NULL
    oauth_id        VARCHAR(255),              -- Entra object ID (oid claim)
    entra_tenant_id VARCHAR(255)               -- tenant van de gebruiker
);

CREATE INDEX idx_users_school ON users(school_id);
CREATE INDEX idx_users_email ON users(email);

-- School jaar (om data per jaar bij te houden)
CREATE TABLE school_years (
    id          SERIAL PRIMARY KEY,
    school_id   INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    label       VARCHAR(20) NOT NULL,           -- bv. "2024-2025"
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE(school_id, label)
);

-- Klassen per school per jaar
CREATE TABLE classes (
    id              SERIAL PRIMARY KEY,
    school_id       INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    school_year_id  INTEGER NOT NULL REFERENCES school_years(id) ON DELETE CASCADE,
    name            VARCHAR(50) NOT NULL,       -- bv. "3A", "4B"
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(school_id, school_year_id, name)
);

-- Koppeling leerkracht aan klas (een leerkracht kan meerdere klassen hebben)
CREATE TABLE teacher_classes (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, class_id)
);

-- Beoordelingen van leerdoelen
CREATE TABLE assessments (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    school_id       INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    school_year_id  INTEGER NOT NULL REFERENCES school_years(id) ON DELETE CASCADE,
    vak_id          VARCHAR(50) NOT NULL,       -- bv. "wiskunde", "nederlands"
    goal_id         VARCHAR(50) NOT NULL,       -- GO! nummer, bv. "WIS.L4.01"
    status          VARCHAR(10) NOT NULL
                    CHECK (status IN ('groen', 'oranje', 'roze')),
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, school_year_id, vak_id, goal_id)
);

CREATE INDEX idx_assessments_school_year ON assessments(school_id, school_year_id);
CREATE INDEX idx_assessments_user ON assessments(user_id);
CREATE INDEX idx_assessments_vak ON assessments(vak_id);

-- Audit log (wie heeft wat gewijzigd)
CREATE TABLE audit_log (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action      VARCHAR(50) NOT NULL,
    details     JSONB,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ================================================
-- SEED DATA - standaard superadmin
-- Wachtwoord wordt gezet via de setup route
-- ================================================
INSERT INTO schools (name, slug) VALUES ('Demo School', 'demo-school');

INSERT INTO users (email, role, first_name, last_name, school_id)
VALUES ('admin@leerdoelen.local', 'superadmin', 'Super', 'Admin', 1);

INSERT INTO school_years (school_id, label, is_active)
VALUES (1, '2024-2025', TRUE);


-- ── Migratie: globale schooljaren (uitvoeren op bestaande installaties) ───────
-- Dit blok is idempotent (IF NOT EXISTS / DO UPDATE) dus veilig om opnieuw te draaien.

-- 1. school_id nullable maken (was NOT NULL)
ALTER TABLE school_years ALTER COLUMN school_id DROP NOT NULL;

-- 2. Unieke constraint op label zodat elk jaar maar één keer bestaat
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'school_years_label_key'
    ) THEN
        ALTER TABLE school_years ADD CONSTRAINT school_years_label_key UNIQUE (label);
    END IF;
END $$;

-- 3. Bestaande jaren zonder school_id=NULL (indien ze al bestaan) behouden
--    Bestaande per-school jaren omzetten naar globale jaren:
UPDATE school_years SET school_id = NULL WHERE school_id IS NOT NULL;
