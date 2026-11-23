-- Back up the selected project database before applying this additive migration.
ALTER TABLE users
    ADD COLUMN height_cm DECIMAL(4,1) NULL,
    ADD COLUMN weight_kg DECIMAL(4,1) NULL,
    ADD COLUMN medical_history_text TEXT NULL,
    ADD COLUMN allergies_text TEXT NULL,
    ADD COLUMN medications_text TEXT NULL,
    ADD COLUMN lifestyle_text TEXT NULL,
    ADD COLUMN health_notes TEXT NULL,
    ADD COLUMN ai_profile_consent BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN profile_context_version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN profile_consent_updated_at BIGINT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS profile_consent_events (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    consented BOOLEAN NOT NULL,
    context_version BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
