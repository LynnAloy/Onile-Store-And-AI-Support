package com.example.mybatisplus.exception;

import org.springframework.http.HttpStatus;

public class PaymentException extends ApiException {
    private final String outcome;
    public PaymentException(int status, String code, String message, String outcome) {
        super(HttpStatus.valueOf(status), code, message);
        this.outcome = outcome;
    }
    public String getOutcome() { return outcome; }
}
