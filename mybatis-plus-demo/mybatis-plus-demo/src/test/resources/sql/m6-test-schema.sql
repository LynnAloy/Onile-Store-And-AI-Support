-- Additive migration. Existing medicine qualifications and wallet permissions are unchanged.
CREATE TABLE IF NOT EXISTS account_roles (
 user_id VARCHAR(36) PRIMARY KEY, role VARCHAR(16) NOT NULL,
 granted_at BIGINT NOT NULL, CHECK (role='ADMIN'),
 FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS medicine_admin_audit (
 id VARCHAR(36) PRIMARY KEY, admin_id VARCHAR(36) NOT NULL, medicine_id INT NOT NULL,
 before_json TEXT NOT NULL, after_json TEXT NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS auto_order_policies (
 user_id VARCHAR(36) PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT FALSE,
 per_order_limit DECIMAL(10,2) NOT NULL DEFAULT 50.00,
 daily_limit DECIMAL(10,2) NOT NULL DEFAULT 200.00,
 version BIGINT NOT NULL DEFAULT 0, parent_hash VARCHAR(64) NULL, updated_at BIGINT NOT NULL,
 CHECK (per_order_limit>0 AND daily_limit>=per_order_limit),
 FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS auto_order_policy_audit (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL,
 before_json TEXT NOT NULL, after_json TEXT NOT NULL, pin_verified BOOLEAN NOT NULL,
 created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS auto_order_turns (
 user_id VARCHAR(36) NOT NULL, turn_id VARCHAR(36) NOT NULL, conversation_id VARCHAR(64) NOT NULL,
 parent_hash VARCHAR(64) NOT NULL, policy_version BIGINT NOT NULL, profile_version BIGINT NOT NULL,
 message_text VARCHAR(4000) NOT NULL, message_hash CHAR(64) NOT NULL,
 request_hash CHAR(64) NULL, status VARCHAR(16) NOT NULL DEFAULT 'READY',
 rejection_code VARCHAR(64) NULL, order_id VARCHAR(30) NULL UNIQUE,
 amount DECIMAL(10,2) NULL, budget_day DATE NULL, created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
 PRIMARY KEY(user_id,turn_id), INDEX idx_auto_budget(user_id,budget_day,status),
 CHECK (status IN ('READY','PAID','REJECTED')),
 FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS medicine_evidence (
 medicine_id INT PRIMARY KEY, version BIGINT NOT NULL, qualification_version BIGINT NOT NULL,
 evidence_json TEXT NOT NULL, reviewed_by VARCHAR(100) NOT NULL, updated_at BIGINT NOT NULL,
 FOREIGN KEY(medicine_id) REFERENCES medicines(id)
);
