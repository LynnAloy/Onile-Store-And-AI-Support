package com.example.mybatisplus.controller;

import com.example.mybatisplus.dto.CommerceRequests;
import com.example.mybatisplus.security.CurrentUser;
import com.example.mybatisplus.service.*;
import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
public class CommerceController {
    private final CurrentUser current;
    private final CommerceAccess access;
    private final MedicineAdminService admin;
    private final AutoOrderService auto;
    public CommerceController(CurrentUser current,CommerceAccess access,MedicineAdminService admin,AutoOrderService auto) {
        this.current=current; this.access=access; this.admin=admin; this.auto=auto;
    }
    private String raw(String auth) { return auth.substring(7); }
    private ResponseEntity<?> response(Object body) { return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body); }
    @GetMapping("/api/account/permissions") public ResponseEntity<?> permissions() {
        return response(Map.of("admin",access.admin(current.actor())));
    }
    @GetMapping("/api/admin/medicines") public ResponseEntity<?> list(@RequestHeader("Authorization") String auth) {
        return response(admin.list(current.actor(),raw(auth)));
    }
    @GetMapping("/api/admin/medicines/{id}/audit") public ResponseEntity<?> audit(@PathVariable int id,@RequestHeader("Authorization") String auth) {
        return response(admin.audit(current.actor(),raw(auth),id));
    }
    @PutMapping("/api/admin/medicines/{id}/qualification") public ResponseEntity<?> review(@PathVariable int id,
            @RequestHeader("Authorization") String auth,@Valid @RequestBody CommerceRequests.Review body) {
        return response(admin.review(current.actor(),raw(auth),id,body));
    }
    @PutMapping("/api/admin/medicines/{id}/stock") public ResponseEntity<?> stock(@PathVariable int id,
            @RequestHeader("Authorization") String auth,@Valid @RequestBody CommerceRequests.Stock body) {
        return response(admin.stock(current.actor(),raw(auth),id,body));
    }
    @GetMapping("/api/wallet/auto-order-policy") public ResponseEntity<?> policy(@RequestHeader("Authorization") String auth) {
        return response(auto.policy(current.actor(),raw(auth)));
    }
    @PutMapping("/api/wallet/auto-order-policy") public ResponseEntity<?> update(@RequestHeader("Authorization") String auth,
            @Valid @RequestBody CommerceRequests.Policy body) { return response(auto.update(current.actor(),raw(auth),body)); }
    @PostMapping("/api/auto-orders/turns") public ResponseEntity<?> register(@RequestHeader("Authorization") String auth,
            @Valid @RequestBody CommerceRequests.Turn body) { return response(auto.register(current.actor(),raw(auth),body)); }
    @GetMapping("/api/auto-orders/turns") public ResponseEntity<?> history(@RequestHeader("Authorization") String auth,
            @RequestParam String conversationId) { return response(auto.history(current.actor(),raw(auth),conversationId)); }
    @PostMapping("/api/auto-orders/turns/{id}/execute") public ResponseEntity<?> execute(@PathVariable String id,
            @RequestHeader("Authorization") String auth,@Valid @RequestBody CommerceRequests.Execute body) {
        return response(auto.execute(current.actor(),raw(auth),id,body));
    }
    @GetMapping("/api/auto-orders/turns/{id}") public ResponseEntity<?> read(@PathVariable String id,@RequestHeader("Authorization") String auth) {
        return response(auto.read(current.actor(),raw(auth),id));
    }
}
