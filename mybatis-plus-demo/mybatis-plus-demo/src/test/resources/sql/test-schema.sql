DROP ALL OBJECTS;
CREATE TABLE users (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(40) NOT NULL UNIQUE,
 password VARCHAR(255) NOT NULL, nickname VARCHAR(50), email VARCHAR(100),
 name VARCHAR(15), age INT, gender VARCHAR(20), birthday VARCHAR(30),
 phone_num VARCHAR(20), address VARCHAR(50), medical_history VARCHAR(4000),
 balance DECIMAL(10,2) NOT NULL DEFAULT 0 CHECK(balance >= 0),
 points INT NOT NULL DEFAULT 0 CHECK(points >= 0),
 wallet_activated BOOLEAN DEFAULT FALSE, walletPassword VARCHAR(255),
 token VARCHAR(255), health_token VARCHAR(255)
 ,height_cm DECIMAL(4,1), weight_kg DECIMAL(4,1), medical_history_text TEXT,
 allergies_text TEXT, medications_text TEXT, lifestyle_text TEXT, health_notes TEXT,
 ai_profile_consent BOOLEAN NOT NULL DEFAULT FALSE,
 profile_context_version BIGINT NOT NULL DEFAULT 0,
 profile_consent_updated_at BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE medicines (
 id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100), price DECIMAL(10,2) NOT NULL,
 stock INT NOT NULL CHECK(stock >= 0),
 sale_classification VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN', review_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
 reference_source VARCHAR(255), reviewed_by VARCHAR(100), qualification_version BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE orders (
 id VARCHAR(30) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id),
 total_price DECIMAL(10,2) NOT NULL, status VARCHAR(20) NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, recipient_name VARCHAR(15),
 recipient_address VARCHAR(50), recipient_phone VARCHAR(20), note VARCHAR(200)
);
CREATE TABLE order_items (
 id BIGINT AUTO_INCREMENT PRIMARY KEY, order_id VARCHAR(30) NOT NULL REFERENCES orders(id),
 medicine_id INT NOT NULL REFERENCES medicines(id), quantity INT NOT NULL CHECK(quantity > 0),
 price DECIMAL(10,2) NOT NULL
);
CREATE TABLE transactions (
 id VARCHAR(30) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id),
 type VARCHAR(20) NOT NULL, amount DECIMAL(10,2), points_change INT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, related_id VARCHAR(50)
);
CREATE TABLE recharge_cards (
 id VARCHAR(20) PRIMARY KEY, amount DECIMAL(10,2) NOT NULL, is_used BOOLEAN DEFAULT FALSE,
 used_by VARCHAR(36) REFERENCES users(id), used_at TIMESTAMP
);
CREATE TABLE message (
 id BIGINT AUTO_INCREMENT PRIMARY KEY, sender VARCHAR(50), content TEXT, created_at TIMESTAMP
);
