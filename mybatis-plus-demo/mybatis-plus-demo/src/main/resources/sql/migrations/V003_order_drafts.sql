-- Run once after backup. Existing products remain unqualified until an operator reviews actual sources.
ALTER TABLE medicines ADD COLUMN sale_classification VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN';
ALTER TABLE medicines ADD COLUMN review_status VARCHAR(16) NOT NULL DEFAULT 'PENDING';
ALTER TABLE medicines ADD COLUMN reference_source VARCHAR(255) NULL;
ALTER TABLE medicines ADD COLUMN reviewed_by VARCHAR(100) NULL;
ALTER TABLE medicines ADD COLUMN qualification_version BIGINT NOT NULL DEFAULT 0;
-- Then run ../m4-draft-schema.sql. local_stack.py prepare applies these additions idempotently.

