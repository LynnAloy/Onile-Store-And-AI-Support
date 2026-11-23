-- H2 MySQL-mode compatibility fixture, derived from the frozen MySQL DDL.
ALTER TABLE orders ADD COLUMN source_draft_id VARCHAR(36) NULL;
ALTER TABLE orders ADD COLUMN payment_status VARCHAR(24) NULL;
ALTER TABLE orders ADD COLUMN payment_version BIGINT NULL;
ALTER TABLE orders ADD COLUMN payment_expires_at BIGINT NULL;
ALTER TABLE orders ADD COLUMN paid_at BIGINT NULL;
ALTER TABLE orders ADD COLUMN closed_at BIGINT NULL;
ALTER TABLE orders ADD COLUMN close_reason VARCHAR(24) NULL;
ALTER TABLE orders ADD UNIQUE KEY uq_orders_source_draft (source_draft_id);
ALTER TABLE orders ADD CONSTRAINT fk_orders_source_draft FOREIGN KEY (source_draft_id) REFERENCES order_drafts(id);
ALTER TABLE orders ADD CONSTRAINT ck_orders_payment CHECK (
  (source_draft_id IS NULL AND payment_status IS NULL AND payment_version IS NULL)
  OR (source_draft_id IS NOT NULL AND payment_status IS NOT NULL
   AND payment_version IS NOT NULL AND payment_version >= 1
   AND payment_expires_at IS NOT NULL AND total_price > 0
   AND ((payment_status='PENDING_PAYMENT' AND paid_at IS NULL AND closed_at IS NULL AND close_reason IS NULL)
    OR (payment_status='PAID' AND paid_at IS NOT NULL AND closed_at IS NULL AND close_reason IS NULL)
    OR (payment_status='CLOSED' AND paid_at IS NULL AND closed_at IS NOT NULL
     AND close_reason IS NOT NULL AND close_reason IN ('USER_CANCELLED','EXPIRED','CATALOG_CHANGED')))));
ALTER TABLE order_items ADD COLUMN name_snapshot VARCHAR(100) NULL;
ALTER TABLE order_items ADD COLUMN qualification_version BIGINT NULL;
CREATE TABLE payment_authorizations (
 id VARCHAR(36) PRIMARY KEY,
 token_hash CHAR(64) NOT NULL UNIQUE,
 user_id VARCHAR(36) NOT NULL,
 parent_hash VARCHAR(64) NOT NULL,
 order_id VARCHAR(30) NOT NULL,
 order_version BIGINT NOT NULL,
 amount DECIMAL(10,2) NOT NULL,
 currency CHAR(3) NOT NULL DEFAULT 'CNY',
 status VARCHAR(16) NOT NULL,
 created_at BIGINT NOT NULL,
 expires_at BIGINT NOT NULL,
 consumed_at BIGINT NULL,
 revoked_at BIGINT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id),
 FOREIGN KEY(parent_hash) REFERENCES auth_sessions(token_hash) ON DELETE CASCADE,
 FOREIGN KEY(order_id) REFERENCES orders(id),
 INDEX idx_payment_auth_order (user_id,order_id,status),
 CONSTRAINT ck_payment_auth CHECK (
  amount > 0 AND currency='CNY' AND order_version >= 1
  AND expires_at > created_at AND expires_at <= created_at+60
  AND ((status='ACTIVE' AND consumed_at IS NULL AND revoked_at IS NULL)
   OR (status='CONSUMED' AND consumed_at IS NOT NULL AND revoked_at IS NULL)
   OR (status='REVOKED' AND consumed_at IS NULL AND revoked_at IS NOT NULL)))
);
CREATE TABLE payment_records (
 id VARCHAR(30) PRIMARY KEY,
 order_id VARCHAR(30) NOT NULL UNIQUE,
 user_id VARCHAR(36) NOT NULL,
 authorization_id VARCHAR(36) NOT NULL,
 ledger_id VARCHAR(30) NOT NULL UNIQUE,
 amount DECIMAL(10,2) NOT NULL,
 currency CHAR(3) NOT NULL DEFAULT 'CNY',
 paid_at BIGINT NOT NULL,
 FOREIGN KEY(order_id) REFERENCES orders(id),
 FOREIGN KEY(user_id) REFERENCES users(id),
 FOREIGN KEY(ledger_id) REFERENCES transactions(id),
 CONSTRAINT ck_payment_record CHECK (amount > 0 AND currency='CNY')
 
);
CREATE TABLE payment_operation_requests (
 user_id VARCHAR(36) NOT NULL,
 operation VARCHAR(16) NOT NULL,
 request_key VARCHAR(64) NOT NULL,
 request_hash CHAR(64) NOT NULL,
 target_id VARCHAR(36) NOT NULL,
 order_id VARCHAR(30) NULL,
 status VARCHAR(16) NOT NULL,
 rejection_code VARCHAR(64) NULL,
 created_at BIGINT NOT NULL,
 PRIMARY KEY(user_id,operation,request_key),
 FOREIGN KEY(user_id) REFERENCES users(id),
 FOREIGN KEY(order_id) REFERENCES orders(id),
 CONSTRAINT ck_payment_request CHECK (
  operation IN ('CHECKOUT','PAY') AND status IN ('REGISTERED','SUCCEEDED','REJECTED')
  AND ((status='SUCCEEDED' AND order_id IS NOT NULL AND rejection_code IS NULL)
   OR (status='REGISTERED' AND rejection_code IS NULL)
   OR (status='REJECTED' AND rejection_code IS NOT NULL)))
);
