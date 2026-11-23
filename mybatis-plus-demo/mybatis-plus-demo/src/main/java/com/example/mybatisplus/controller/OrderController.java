package com.example.mybatisplus.controller;

import com.example.mybatisplus.dto.OrderDTO;
import com.example.mybatisplus.entity.Order;
import com.example.mybatisplus.security.CredentialVerifier;
import com.example.mybatisplus.security.CurrentUser;
import com.example.mybatisplus.service.OrderService;
import jakarta.validation.Valid;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.*;
import com.example.mybatisplus.exception.ApiException;

@RestController
@RequestMapping("/api/orders")
public class OrderController {
    private final OrderService orders;
    private final CurrentUser current;
    private final CredentialVerifier verifier;
    private final com.example.mybatisplus.service.PaymentService payments;

    public OrderController(OrderService orders, CurrentUser current, CredentialVerifier verifier,
                           com.example.mybatisplus.service.PaymentService payments) {
        this.orders = orders;
        this.current = current;
        this.verifier = verifier;
        this.payments = payments;
    }

    @PostMapping
    public Map<String, Object> submit(@Valid @RequestBody OrderDTO request,
                                      @RequestHeader("Idempotency-Key") String requestKey) {
        if (payments.enabled()) throw new ApiException(org.springframework.http.HttpStatus.CONFLICT,
                "LEGACY_CHECKOUT_DISABLED", "请从确认后的草稿进入独立支付流程");
        if (!requestKey.matches("[A-Za-z0-9_-]{8,64}")) throw new ApiException("请求幂等键不合法");
        String username = current.username(request.getUserId());
        verifier.verify(username, request.getWalletPassword(), true);
        return orders.submitOrder(username, request, requestKey);
    }

    @GetMapping
    public Object search(@RequestParam(required = false) String phone,
                         @RequestParam(required = false) String userId, @RequestHeader("Authorization") String auth) {
        current.username(userId);
        if (payments.enabled()) return org.springframework.http.ResponseEntity.ok()
                .cacheControl(org.springframework.http.CacheControl.noStore())
                .body(payments.list(current.actor(),auth.substring(7),phone));
        return orders.searchOrders(current.username(userId), phone);
    }

    @GetMapping("/{orderId}")
    public Object get(@PathVariable String orderId, @RequestHeader("Authorization") String auth,
                      @RequestParam(required=false) String paymentRequestKey) {
        if (payments.enabled()) return org.springframework.http.ResponseEntity.ok()
                .cacheControl(org.springframework.http.CacheControl.noStore())
                .body(payments.read(current.actor(), auth.substring(7), orderId, paymentRequestKey));
        return orders.getOrder(current.username(null), orderId);
    }

    @DeleteMapping("/{orderId}")
    public void delete(@PathVariable String orderId) {
        orders.deleteOrder(current.username(null), orderId);
    }
}
