package com.example.mybatisplus.service;

import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.security.Actor;
import com.example.mybatisplus.security.SessionService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.constraints.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MedicineEvidenceService {
    private final JdbcTemplate db;
    private final CommerceAccess access;
    private final ObjectMapper json;
    private final boolean enabled;
    public record Evidence(@NotNull @Min(0) Long expectedVersion, @NotNull @Min(0) Long qualificationVersion,
            @NotEmpty @Size(max=20) List<@NotBlank @Size(max=50) String> categories,
            @NotEmpty @Size(max=30) List<@NotBlank @Size(max=100) String> ingredients,
            @NotBlank @Size(max=2000) String indications, @NotBlank @Size(max=500) String source,
            @NotNull @Min(1) @Max(99) Integer maxUnitsPerOrder) {}
    public MedicineEvidenceService(JdbcTemplate db,CommerceAccess access,ObjectMapper json,
            @Value("${commerce.evidence-enabled:false}") boolean enabled) {
        this.db=db; this.access=access; this.json=json; this.enabled=enabled;
    }
    public Map<String,Object> read(int id,long qualificationVersion) {
        if (!enabled) return Map.of();
        boolean locked=org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive();
        var rows=db.queryForList("SELECT * FROM medicine_evidence WHERE medicine_id=?"+(locked?" FOR UPDATE":""),id);
        if (rows.isEmpty()) return Map.of();
        var row=rows.getFirst();
        if (((Number)row.get("qualification_version")).longValue()!=qualificationVersion) return Map.of();
        try {
            Map<String,Object> result=json.readValue((String)row.get("evidence_json"),new com.fasterxml.jackson.core.type.TypeReference<>() {});
            result.put("version",row.get("version")); result.put("reviewedBy",row.get("reviewed_by"));
            result.put("qualificationVersion",qualificationVersion); result.put("status","APPROVED");
            return result;
        } catch (java.io.IOException ex) { throw new IllegalStateException("Evidence invalid",ex); }
    }
    public Map<String,Object> adminRead(Actor actor,String raw,int id) {
        access.requireAdmin(actor,raw);
        Long version=db.queryForObject("SELECT qualification_version FROM medicines WHERE id=?",Long.class,id);
        var valid=read(id,version);
        if (!valid.isEmpty()) return valid;
        if (!enabled) return Map.of();
        var rows=db.queryForList("SELECT * FROM medicine_evidence WHERE medicine_id=?",id);
        if (rows.isEmpty()) return Map.of("version",0,"qualificationVersion",version);
        try {
            Map<String,Object> result=json.readValue((String)rows.getFirst().get("evidence_json"),new com.fasterxml.jackson.core.type.TypeReference<>() {});
            result.put("version",rows.getFirst().get("version")); result.put("qualificationVersion",version); result.put("status","STALE");
            return result;
        } catch (java.io.IOException ex) { throw new IllegalStateException(ex); }
    }
    @Transactional public Map<String,Object> save(Actor actor,String raw,int id,Evidence body) {
        access.requireAdmin(actor,raw);
        if (!enabled) throw new ApiException("药品证据功能尚未启用");
        db.queryForMap("SELECT id FROM users WHERE id=? FOR UPDATE",actor.id());
        var medicine=db.queryForMap("SELECT qualification_version FROM medicines WHERE id=? FOR UPDATE",id);
        if (((Number)medicine.get("qualification_version")).longValue()!=body.qualificationVersion())
            throw new ApiException(HttpStatus.CONFLICT,"VERSION_CONFLICT","商品审核版本已变化");
        var rows=db.queryForList("SELECT * FROM medicine_evidence WHERE medicine_id=? FOR UPDATE",id);
        long old=rows.isEmpty()?0:((Number)rows.getFirst().get("version")).longValue();
        if (old!=body.expectedVersion()) throw new ApiException(HttpStatus.CONFLICT,"VERSION_CONFLICT","证据版本已变化");
        if (!body.source().matches("(https?://|local://)\\S+")) throw new ApiException("请填写可追溯说明书或审核资料地址");
        try {
            String encoded=json.writeValueAsString(Map.of("categories",body.categories(),"ingredients",body.ingredients(),
                    "indications",body.indications(),"source",body.source(),"maxUnitsPerOrder",body.maxUnitsPerOrder()));
            long now=java.time.Instant.now().getEpochSecond();
            if (rows.isEmpty()) db.update("INSERT INTO medicine_evidence VALUES (?,?,?,?,?,?)",id,old+1,body.qualificationVersion(),encoded,actor.username(),now);
            else db.update("UPDATE medicine_evidence SET version=?,qualification_version=?,evidence_json=?,reviewed_by=?,updated_at=? WHERE medicine_id=?",old+1,body.qualificationVersion(),encoded,actor.username(),now,id);
            db.update("INSERT INTO medicine_admin_audit VALUES (?,?,?,?,?,?)",UUID.randomUUID().toString(),actor.id(),id,
                    rows.isEmpty()?"{}":(String)rows.getFirst().get("evidence_json"),encoded,now);
        } catch (java.io.IOException ex) { throw new IllegalStateException(ex); }
        access.requireAdmin(actor,raw);
        return read(id,body.qualificationVersion());
    }
}
