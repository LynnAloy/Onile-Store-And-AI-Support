package com.example.mybatisplus.controller;

import com.example.mybatisplus.dto.DraftRequests;
import com.example.mybatisplus.security.CurrentUser;
import com.example.mybatisplus.service.DraftService;
import jakarta.validation.Valid;
import java.util.List;
import java.util.Map;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
public class DraftController {
    private final DraftService drafts;
    private final CurrentUser current;
    public DraftController(DraftService drafts, CurrentUser current) {
        this.drafts = drafts;
        this.current = current;
    }
    private String raw(String header) { return header.substring(7); }
    private <T> ResponseEntity<T> noStore(T data) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(data);
    }

    @PostMapping("/api/auth/order-agent-token")
    public ResponseEntity<?> grant(@RequestHeader("Authorization") String auth,
                                   @Valid @RequestBody DraftRequests.Intent request) {
        return noStore(drafts.grant(current.actor(), raw(auth), request));
    }
    @DeleteMapping("/api/auth/order-agent-token")
    public ResponseEntity<?> revoke(@RequestHeader("Authorization") String auth,
                                   @RequestParam(required = false) String requestKey) {
        drafts.revoke(current.actor(), raw(auth), requestKey);
        return noStore(Map.of("revoked", true));
    }
    @GetMapping("/internal/ai/v1/order-preparation")
    public ResponseEntity<?> capability(@RequestHeader("Authorization") String auth) {
        return noStore(drafts.capability(current.actor(), raw(auth)));
    }
    @PostMapping("/internal/ai/v1/order-drafts")
    public ResponseEntity<?> prepare(@RequestHeader("Authorization") String auth,
                                    @RequestHeader("Idempotency-Key") String key,
                                    @Valid @RequestBody DraftRequests.Intent request) {
        return noStore(drafts.prepare(current.actor(), raw(auth), request, key));
    }
    @GetMapping("/api/order-drafts")
    public ResponseEntity<?> list(@RequestHeader("Authorization") String auth,
                                 @RequestParam(required = false) String requestKey) {
        if (requestKey != null && !requestKey.matches("[A-Za-z0-9_-]{1,64}")) {
            throw new com.example.mybatisplus.exception.ApiException("请求键格式不正确");
        }
        return noStore(drafts.list(current.actor(), raw(auth), requestKey));
    }
    @GetMapping("/api/order-drafts/{id}")
    public ResponseEntity<?> get(@RequestHeader("Authorization") String auth, @PathVariable String id) {
        return noStore(drafts.get(current.actor(), raw(auth), id));
    }
    @PostMapping("/api/order-drafts/{id}/confirm")
    public ResponseEntity<?> confirm(@RequestHeader("Authorization") String auth, @PathVariable String id,
                                    @Valid @RequestBody DraftRequests.Confirm request) {
        return noStore(drafts.confirm(current.actor(), raw(auth), id, request));
    }
    @PostMapping("/api/order-drafts/{id}/cancel")
    public ResponseEntity<?> cancel(@RequestHeader("Authorization") String auth, @PathVariable String id,
                                   @Valid @RequestBody DraftRequests.Version request) {
        return noStore(drafts.cancel(current.actor(), raw(auth), id, request.version()));
    }
}

