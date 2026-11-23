CREATE TABLE IF NOT EXISTS medicine_evidence (
 medicine_id INT PRIMARY KEY, version BIGINT NOT NULL, qualification_version BIGINT NOT NULL,
 evidence_json TEXT NOT NULL, reviewed_by VARCHAR(100) NOT NULL, updated_at BIGINT NOT NULL,
 FOREIGN KEY(medicine_id) REFERENCES medicines(id)
);
