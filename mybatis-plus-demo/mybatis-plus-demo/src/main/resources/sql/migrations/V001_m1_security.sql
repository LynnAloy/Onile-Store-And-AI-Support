-- Run manually once against the existing DeepSeekDoc schema; back up first.
-- This project does not enable automatic DDL/migrations.
ALTER TABLE users MODIFY password VARCHAR(255) NOT NULL;
ALTER TABLE users MODIFY walletPassword VARCHAR(255) NULL;
UPDATE users SET token=NULL, health_token=NULL;
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    scope VARCHAR(20) NOT NULL,
    parent_hash VARCHAR(64),
    expires_at BIGINT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_session_user (user_id),
    INDEX idx_session_parent (parent_hash)
);
CREATE TABLE IF NOT EXISTS security_attempts (
    attempt_key VARCHAR(100) PRIMARY KEY,
    failures INT NOT NULL DEFAULT 0,
    locked_until BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS checkout_requests (
    user_id VARCHAR(36) NOT NULL,
    request_key VARCHAR(64) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    order_id VARCHAR(30) NOT NULL,
    PRIMARY KEY (user_id, request_key),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (order_id) REFERENCES orders(id)
);
