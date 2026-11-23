package com.example.mybatisplus.config;

import com.example.mybatisplus.service.PaymentService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class CommerceSchemaGuard implements ApplicationRunner {
    private final boolean enabled;
    private final PaymentService payments;
    private final JdbcTemplate db;
    public CommerceSchemaGuard(@Value("${commerce.enabled:false}") boolean enabled, PaymentService payments, JdbcTemplate db) {
        this.enabled=enabled; this.payments=payments; this.db=db;
    }
    @Override public void run(ApplicationArguments args) {
        if (!enabled) return;
        if (!payments.enabled()) throw new IllegalStateException("Commerce requires the verified payment engine");
        for (String table:new String[]{"account_roles","medicine_admin_audit","auto_order_policies","auto_order_policy_audit","auto_order_turns"})
            db.queryForList("SELECT * FROM "+table+" WHERE 1=0");
    }
}
