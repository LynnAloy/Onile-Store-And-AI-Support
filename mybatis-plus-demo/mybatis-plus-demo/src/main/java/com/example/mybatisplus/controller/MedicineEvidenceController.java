package com.example.mybatisplus.controller;
import com.example.mybatisplus.service.MedicineEvidenceService;
import com.example.mybatisplus.security.CurrentUser;
import jakarta.validation.Valid;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
@RestController
public class MedicineEvidenceController {
    private final MedicineEvidenceService service;
    private final CurrentUser current;
    public MedicineEvidenceController(MedicineEvidenceService service,CurrentUser current) { this.service=service; this.current=current; }
    @GetMapping("/api/admin/medicines/{id}/evidence") public ResponseEntity<?> get(@PathVariable int id,@RequestHeader("Authorization") String auth) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(service.adminRead(current.actor(),auth.substring(7),id));
    }
    @PutMapping("/api/admin/medicines/{id}/evidence") public ResponseEntity<?> put(@PathVariable int id,@RequestHeader("Authorization") String auth,@Valid @RequestBody MedicineEvidenceService.Evidence body) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(service.save(current.actor(),auth.substring(7),id,body));
    }
}
