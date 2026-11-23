package com.example.mybatisplus.service;

import com.example.mybatisplus.dto.CommerceRequests;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.security.Actor;
import com.example.mybatisplus.security.SessionService;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MedicineAdminService {
    private final JdbcTemplate db;
    private final CommerceAccess access;
    private final SessionService sessions;
    private final ObjectMapper json;
    public MedicineAdminService(JdbcTemplate db, CommerceAccess access, SessionService sessions, ObjectMapper json) {
        this.db=db; this.access=access; this.sessions=sessions; this.json=json;
    }
    public List<Map<String,Object>> list(Actor actor,String raw) {
        access.requireAdmin(actor,raw);
        return db.queryForList("SELECT id,name,price,stock,sale_classification,review_status,reference_source,reviewed_by,qualification_version FROM medicines ORDER BY id LIMIT 500");
    }
    public List<Map<String,Object>> audit(Actor actor,String raw,int id) {
        access.requireAdmin(actor,raw);
        return db.queryForList("SELECT * FROM medicine_admin_audit WHERE medicine_id=? ORDER BY created_at DESC,id LIMIT 50",id);
    }
    private Map<String,Object> locked(Actor actor,String raw,int id,long version) {
        db.queryForMap("SELECT id FROM users WHERE id=? FOR UPDATE",actor.id());
        access.requireAdmin(actor,raw);
        var rows=db.queryForList("SELECT * FROM medicines WHERE id=? FOR UPDATE",id);
        if (rows.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND,"MEDICINE_NOT_FOUND","商品不存在");
        var row=rows.getFirst();
        if (((Number)row.get("qualification_version")).longValue()!=version)
            throw new ApiException(HttpStatus.CONFLICT,"VERSION_CONFLICT","商品已被修改，请刷新后重试");
        return row;
    }
    private void record(Actor actor,String raw,int id,Map<String,Object> before,String reason) {
        access.requireAdmin(actor,raw);
        var after=db.queryForMap("SELECT * FROM medicines WHERE id=?",id);
        after.put("changeReason",reason);
        try {
            db.update("INSERT INTO medicine_admin_audit VALUES (?,?,?,?,?,?)",UUID.randomUUID().toString(),actor.id(),id,
                    json.writeValueAsString(before),json.writeValueAsString(after),sessions.now());
        } catch (com.fasterxml.jackson.core.JsonProcessingException ex) { throw new IllegalStateException("Audit serialization failed",ex); }
    }
    @Transactional public Map<String,Object> review(Actor actor,String raw,int id,CommerceRequests.Review body) {
        var before=locked(actor,raw,id,body.expectedVersion());
        String source=body.referenceSource()==null ? "" : body.referenceSource().trim();
        if ("APPROVED".equals(body.reviewStatus()) && ("UNKNOWN".equals(body.classification())
                || !source.matches("(https?://|local://)\\S+"))) throw new ApiException("审核通过必须填写明确分类及可追溯审核依据");
        db.update("UPDATE medicines SET sale_classification=?,review_status=?,reference_source=?,reviewed_by=?,qualification_version=qualification_version+1 WHERE id=?",
                body.classification(),body.reviewStatus(),source,actor.username(),id);
        record(actor,raw,id,before,"QUALIFICATION_REVIEW");
        return db.queryForMap("SELECT * FROM medicines WHERE id=?",id);
    }
    @Transactional public Map<String,Object> stock(Actor actor,String raw,int id,CommerceRequests.Stock body) {
        var before=locked(actor,raw,id,body.expectedVersion());
        if (((Number)before.get("stock")).intValue()!=body.expectedStock())
            throw new ApiException(HttpStatus.CONFLICT,"STOCK_CHANGED","库存已因销售或调整发生变化，请刷新后核对");
        db.update("UPDATE medicines SET stock=?,qualification_version=qualification_version+1 WHERE id=?",body.stock(),id);
        record(actor,raw,id,before,body.reason());
        return db.queryForMap("SELECT * FROM medicines WHERE id=?",id);
    }
}
