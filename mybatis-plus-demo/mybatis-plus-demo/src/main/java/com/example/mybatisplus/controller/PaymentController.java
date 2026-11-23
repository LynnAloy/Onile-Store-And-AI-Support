package com.example.mybatisplus.controller;

import com.example.mybatisplus.dto.PaymentRequests;
import com.example.mybatisplus.security.CurrentUser;
import com.example.mybatisplus.service.PaymentService;
import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
public class PaymentController {
    private final PaymentService payments;
    private final CurrentUser current;
    public PaymentController(PaymentService payments, CurrentUser current) { this.payments = payments; this.current = current; }
    private String raw(String auth) { return auth.substring(7); }
    private ResponseEntity<?> response(Map<String,Object> body) { return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body); }
    @ExceptionHandler({org.springframework.web.bind.MethodArgumentNotValidException.class,
        org.springframework.http.converter.HttpMessageNotReadableException.class,
        org.springframework.web.bind.MissingRequestHeaderException.class,
        org.springframework.web.method.annotation.HandlerMethodValidationException.class})
    public ResponseEntity<?> invalidRequest(Exception ex) {
        return ResponseEntity.badRequest().cacheControl(CacheControl.noStore()).body(
                Map.of("code","INVALID_REQUEST","message","请求参数不合法或缺少必填字段","outcome","NOT_APPLIED"));
    }
    @PostMapping("/api/order-drafts/{id}/checkout")
    public ResponseEntity<?> checkout(@PathVariable String id, @RequestHeader("Authorization") String auth,
            @RequestHeader("Idempotency-Key") String key, @Valid @RequestBody PaymentRequests.Version body) {
        return response(payments.checkout(current.actor(),raw(auth),id,body.expectedVersion(),key));
    }
    @PostMapping("/api/orders/{id}/payment-authorizations")
    public ResponseEntity<?> authorize(@PathVariable String id, @RequestHeader("Authorization") String auth,
            @Valid @RequestBody PaymentRequests.Authorize body) {
        return response(payments.authorize(current.actor(),raw(auth),id,body.expectedVersion(),body.password()));
    }
    @DeleteMapping("/api/orders/{id}/payment-authorizations")
    public ResponseEntity<?> revoke(@PathVariable String id, @RequestHeader("Authorization") String auth,
            @RequestParam(required=false) String authorizationId) {
        return response(payments.revoke(current.actor(),raw(auth),id,authorizationId));
    }
    @PostMapping("/api/orders/{id}/pay")
    public ResponseEntity<?> pay(@PathVariable String id, @RequestHeader("Authorization") String auth,
            @RequestHeader("X-Payment-Authorization") String token, @RequestHeader("Idempotency-Key") String key,
            @Valid @RequestBody PaymentRequests.Version body) {
        return response(payments.pay(current.actor(),raw(auth),id,body.expectedVersion(),key,token));
    }
    @PostMapping("/api/orders/{id}/close")
    public ResponseEntity<?> close(@PathVariable String id, @RequestHeader("Authorization") String auth,
            @Valid @RequestBody PaymentRequests.Version body) {
        return response(payments.close(current.actor(),raw(auth),id,body.expectedVersion()));
    }
}
