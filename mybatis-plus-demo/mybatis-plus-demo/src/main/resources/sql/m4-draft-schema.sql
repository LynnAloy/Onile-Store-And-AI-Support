CREATE TABLE IF NOT EXISTS order_agent_grants (
 token_hash VARCHAR(64) PRIMARY KEY,
 user_id VARCHAR(36) NOT NULL, intent_json TEXT NOT NULL,
 request_key VARCHAR(64) NOT NULL UNIQUE, expires_at BIGINT NOT NULL,
 FOREIGN KEY(token_hash) REFERENCES auth_sessions(token_hash) ON DELETE CASCADE,
 FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS order_drafts (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL,
 grant_hash VARCHAR(64) NOT NULL UNIQUE, request_key VARCHAR(64) NOT NULL,
 request_hash VARCHAR(64) NOT NULL, status VARCHAR(16) NOT NULL,
 version BIGINT NOT NULL, total_price DECIMAL(10,2) NOT NULL,
 created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
 recipient_name VARCHAR(15), recipient_phone VARCHAR(20), recipient_address VARCHAR(50),
 confirmation_hash VARCHAR(64),
 UNIQUE(user_id, request_key), FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS order_draft_items (
 draft_id VARCHAR(36) NOT NULL,
 medicine_id INT NOT NULL, name VARCHAR(100) NOT NULL,
 quantity INT NOT NULL, price DECIMAL(10,2) NOT NULL, qualification_version BIGINT NOT NULL,
 PRIMARY KEY(draft_id,medicine_id), FOREIGN KEY(draft_id) REFERENCES order_drafts(id),
 FOREIGN KEY(medicine_id) REFERENCES medicines(id)
);

