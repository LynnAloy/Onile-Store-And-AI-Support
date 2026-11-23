package com.example.mybatisplus.config;

import com.example.mybatisplus.service.PaymentService;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class PaymentSchemaGuard implements ApplicationRunner {
    private final PaymentService payments;
    private final JdbcTemplate db;
    public PaymentSchemaGuard(PaymentService payments, JdbcTemplate db) { this.payments = payments; this.db = db; }
    @Override public void run(ApplicationArguments args) {
        if (!payments.enabled()) {
            Integer exists = db.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='payment_records'",Integer.class);
            if (exists>0 && db.queryForObject("SELECT COUNT(*) FROM payment_records",Long.class)>0) {
                throw new IllegalStateException("Paid audit records exist; refusing rollback to legacy checkout");
            }
            return;
        }
        db.queryForList("SELECT payment_status,payment_version,source_draft_id FROM orders WHERE 1=0");
        db.queryForList("SELECT name_snapshot,qualification_version FROM order_items WHERE 1=0");
        for (String table : new String[]{"payment_authorizations","payment_records","payment_operation_requests"})
            db.queryForList("SELECT * FROM " + table + " WHERE 1=0");
    }
}
