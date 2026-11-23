package com.example.mybatisplus.service;

import org.springframework.stereotype.Component;

/** Transaction fault injection seam for tests; no HTTP endpoint or runtime switch. */
@Component
public class PaymentHooks {
    public void afterDebit(String orderId) {}
}
