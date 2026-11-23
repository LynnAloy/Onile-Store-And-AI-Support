package com.example.mybatisplus.config;

import com.example.mybatisplus.service.PaymentReconciliationService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;

@Configuration
@EnableScheduling
@ConditionalOnProperty(name="payments.recovery-scheduling-enabled", havingValue="true", matchIfMissing=true)
public class PaymentRecoveryScheduler {
    private final PaymentReconciliationService recovery;
    public PaymentRecoveryScheduler(PaymentReconciliationService recovery) { this.recovery = recovery; }
    @Scheduled(fixedDelay=15000, initialDelay=15000)
    public void reconcile() { recovery.reconcile(); }
}
