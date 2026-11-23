package com.example.mybatisplus.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.example.mybatisplus.dto.DraftRequests;
import com.example.mybatisplus.entity.Medicine;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.mapper.MedicineMapper;
import com.example.mybatisplus.security.Actor;
import com.example.mybatisplus.security.SessionService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class DraftService {
    private final JdbcTemplate jdbc;
    private final SessionService sessions;
    private final MedicineMapper medicines;
    private final ObjectMapper json;

    public DraftService(JdbcTemplate jdbc, SessionService sessions, MedicineMapper medicines, ObjectMapper json) {
        this.jdbc = jdbc;
        this.sessions = sessions;
        this.medicines = medicines;
        this.json = json;
    }

    private ApiException conflict(String code, String message) {
        return new ApiException(HttpStatus.CONFLICT, code, message);
    }

    private void lock(Actor actor, String raw) {
        jdbc.queryForObject("SELECT id FROM users WHERE id=? FOR UPDATE", String.class, actor.id());
        Actor fresh = sessions.resolve(raw);
        if (fresh == null || !fresh.sessionHash().equals(actor.sessionHash())) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "UNAUTHORIZED", "授权已失效");
        }
    }

    public List<DraftRequests.Item> canonical(DraftRequests.Intent request) {
        TreeMap<Integer, Integer> items = new TreeMap<>();
        for (var item : request.items()) {
            if (items.put(item.medicineId(), item.quantity()) != null) {
                throw new ApiException("同一商品不能重复提交");
            }
        }
        return items.entrySet().stream().map(e -> new DraftRequests.Item(e.getKey(), e.getValue())).toList();
    }

    private String encode(Object value) {
        try { return json.writeValueAsString(value); }
        catch (Exception ex) { throw new IllegalStateException("Cannot serialize draft metadata"); }
    }

    @Transactional
    public Map<String, Object> grant(Actor actor, String raw, DraftRequests.Intent request) {
        lock(actor, raw);
        var intent = canonical(request);
        jdbc.update("DELETE FROM auth_sessions WHERE user_id=? AND scope='AGENT_ORDER_PREPARE' AND expires_at<=?",
                actor.id(), sessions.now());
        Integer active = jdbc.queryForObject("SELECT COUNT(*) FROM order_agent_grants WHERE user_id=?",
                Integer.class, actor.id());
        if (active >= 10) throw new ApiException(HttpStatus.TOO_MANY_REQUESTS, "TOO_MANY_GRANTS", "订单准备授权过多，请先撤销");
        Map<String, Object> delegated = sessions.delegateOrder(actor);
        String key = UUID.randomUUID().toString();
        jdbc.update("INSERT INTO order_agent_grants VALUES (?,?,?,?,?)",
                SessionService.digest((String) delegated.get("token")), actor.id(), encode(intent), key,
                delegated.get("expiresAt"));
        Map<String, Object> result = new LinkedHashMap<>(delegated);
        result.put("items", intent);
        result.put("requestKey", key);
        return result;
    }

    @Transactional
    public void revoke(Actor actor, String raw, String requestKey) {
        lock(actor, raw);
        if (requestKey == null) {
            jdbc.update("DELETE FROM auth_sessions WHERE user_id=? AND scope='AGENT_ORDER_PREPARE'", actor.id());
        } else {
            if (!requestKey.matches("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")) {
                throw new ApiException("订单准备请求键格式无效");
            }
            jdbc.update("DELETE FROM auth_sessions WHERE user_id=? AND scope='AGENT_ORDER_PREPARE' "
                    + "AND token_hash IN (SELECT token_hash FROM order_agent_grants WHERE user_id=? AND request_key=?)",
                    actor.id(), actor.id(), requestKey);
        }
    }

    private Map<String, Object> grantRow(Actor actor) {
        var rows = jdbc.queryForList("SELECT * FROM order_agent_grants WHERE token_hash=? AND user_id=? AND expires_at>?",
                actor.sessionHash(), actor.id(), sessions.now());
        if (rows.isEmpty()) throw new ApiException(HttpStatus.UNAUTHORIZED, "UNAUTHORIZED", "订单准备授权已失效");
        return rows.getFirst();
    }

    @Transactional
    public Map<String, Object> capability(Actor actor, String raw) {
        lock(actor, raw);
        var row = grantRow(actor);
        try {
            List<DraftRequests.Item> intent = json.readValue((String) row.get("intent_json"), new TypeReference<>() {});
            return Map.of("userId", actor.username(), "scope", actor.scope(), "items", intent,
                    "requestKey", row.get("request_key"), "expiresAt", row.get("expires_at"));
        } catch (Exception ex) { throw new IllegalStateException("Invalid stored order intent"); }
    }

    @Transactional
    public Map<String, Object> prepare(Actor actor, String raw, DraftRequests.Intent request, String key) {
        lock(actor, raw);
        var grant = grantRow(actor);
        String intent = encode(canonical(request));
        if (!intent.equals(grant.get("intent_json"))) throw conflict("INTENT_MISMATCH", "商品或数量与用户授权不符");
        if (!Objects.equals(key, grant.get("request_key"))) throw conflict("IDEMPOTENCY_CONFLICT", "请求键与授权不符");
        String fingerprint = SessionService.digest(intent);
        var previous = jdbc.queryForList("SELECT * FROM order_drafts WHERE user_id=? AND request_key=?",
                actor.id(), key);
        if (!previous.isEmpty()) {
            if (!fingerprint.equals(previous.getFirst().get("request_hash"))) {
                throw conflict("IDEMPOTENCY_CONFLICT", "相同请求键不能对应不同草稿");
            }
            return view(previous.getFirst(), false);
        }
        List<Map<String, Object>> lines = new ArrayList<>();
        BigDecimal total = BigDecimal.ZERO;
        for (var item : canonical(request)) {
            Medicine medicine = medicines.selectOne(new QueryWrapper<Medicine>()
                    .eq("id", item.medicineId()).last("FOR UPDATE"));
            SalePolicy.require(medicine);
            if (medicine.getStock() < item.quantity()) throw conflict("OUT_OF_STOCK", "商品库存不足");
            BigDecimal price = medicine.getPrice();
            total = total.add(price.multiply(BigDecimal.valueOf(item.quantity())));
            lines.add(Map.of("medicine", medicine, "quantity", item.quantity()));
        }
        if (total.compareTo(new BigDecimal("99999999.99")) > 0) throw new ApiException("草稿金额过大");
        lock(actor, raw);
        String id = UUID.randomUUID().toString();
        long now = sessions.now();
        jdbc.update("INSERT INTO order_drafts(id,user_id,grant_hash,request_key,request_hash,status,version,"
                + "total_price,created_at,expires_at) VALUES (?,?,?,?,?,'PREPARED',1,?,?,?)",
                id, actor.id(), actor.sessionHash(), key, fingerprint, total, now, now + 900);
        for (var line : lines) {
            Medicine medicine = (Medicine) line.get("medicine");
            jdbc.update("INSERT INTO order_draft_items VALUES (?,?,?,?,?,?)", id, medicine.getId(),
                    medicine.getName(), line.get("quantity"), medicine.getPrice(), medicine.getQualificationVersion());
        }
        return view(owned(actor, id), false);
    }

    private Map<String, Object> owned(Actor actor, String id) {
        var rows = jdbc.queryForList("SELECT * FROM order_drafts WHERE id=? AND user_id=? FOR UPDATE", id, actor.id());
        if (rows.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "草稿不存在");
        return rows.getFirst();
    }

    private String state(Map<String, Object> row) {
        String status = (String) row.get("status");
        return status.equals("PREPARED") && ((Number) row.get("expires_at")).longValue() <= sessions.now()
                ? "EXPIRED" : status;
    }

    private Map<String, Object> view(Map<String, Object> row, boolean privateView) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("draftId", row.get("id"));
        result.put("requestKey", row.get("request_key"));
        result.put("status", state(row));
        result.put("version", row.get("version"));
        result.put("totalPrice", ((BigDecimal) row.get("total_price")).toPlainString());
        result.put("currency", "CNY");
        result.put("expiresAt", row.get("expires_at"));
        result.put("createdAt", row.get("created_at"));
        result.put("paid", false);
        var rows = jdbc.queryForList("SELECT * FROM order_draft_items WHERE draft_id=? ORDER BY medicine_id", row.get("id"));
        List<Map<String, Object>> items = new ArrayList<>();
        List<String> reasons = new ArrayList<>();
        BigDecimal currentTotal = BigDecimal.ZERO;
        for (var line : rows) {
            Medicine medicine = medicines.selectById((Integer) line.get("medicine_id"));
            String blocked = SalePolicy.reason(medicine);
            int quantity = ((Number) line.get("quantity")).intValue();
            if (blocked == null && medicine.getStock() < quantity) blocked = "商品库存不足";
            if (blocked == null && medicine.getPrice().compareTo((BigDecimal) line.get("price")) != 0) blocked = "商品价格已变化，请重新准备草稿";
            if (blocked == null && !Objects.equals(medicine.getQualificationVersion(),
                    ((Number) line.get("qualification_version")).longValue())) blocked = "商品审核版本已变化，请重新准备草稿";
            if (blocked != null) reasons.add(blocked);
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("medicineId", line.get("medicine_id"));
            item.put("name", line.get("name"));
            item.put("quantity", quantity);
            item.put("price", ((BigDecimal) line.get("price")).toPlainString());
            if (privateView) {
                item.put("currentPrice", medicine == null ? null : medicine.getPrice());
                item.put("currentStock", medicine == null ? 0 : medicine.getStock());
                item.put("blockedReason", blocked);
            }
            if (medicine != null) currentTotal = currentTotal.add(medicine.getPrice().multiply(BigDecimal.valueOf(quantity)));
            items.add(item);
        }
        result.put("items", items);
        if (privateView) {
            result.put("canConfirm", state(row).equals("PREPARED") && reasons.isEmpty());
            result.put("blockingReasons", reasons);
            result.put("currentTotal", currentTotal.toPlainString());
            result.put("recipientName", row.get("recipient_name"));
            result.put("recipientPhone", row.get("recipient_phone"));
            result.put("recipientAddress", row.get("recipient_address"));
        }
        return result;
    }

    @Transactional
    public Map<String, Object> get(Actor actor, String raw, String id) {
        lock(actor, raw);
        var row = owned(actor, id);
        var result = view(row, true);
        if ("PREPARED".equals(result.get("status"))) {
            var profiles = jdbc.queryForList(
                    "SELECT name, phone_num, address FROM users WHERE id=? AND ai_profile_consent=TRUE", actor.id());
            if (!profiles.isEmpty()) {
                var profile = profiles.getFirst();
                prefill(result, "recipientName", profile.get("name"), 15);
                prefill(result, "recipientPhone", profile.get("phone_num"), 11);
                prefill(result, "recipientAddress", profile.get("address"), 50);
            }
        }
        return result;
    }

    private void prefill(Map<String, Object> result, String key, Object value, int maxLength) {
        if (result.get(key) != null || !(value instanceof String text)) return;
        String clean = text.strip();
        if (clean.isEmpty() || clean.length() > maxLength) return;
        if ("recipientPhone".equals(key) && !clean.matches("1[3-9][0-9]{9}")) return;
        result.put(key, clean);
        result.put("shippingPrefilled", true);
    }

    @Transactional
    public List<Map<String, Object>> list(Actor actor, String raw, String key) {
        lock(actor, raw);
        var rows = key == null ? jdbc.queryForList("SELECT * FROM order_drafts WHERE user_id=? ORDER BY created_at DESC,id LIMIT 50", actor.id())
                : jdbc.queryForList("SELECT * FROM order_drafts WHERE user_id=? AND request_key=?", actor.id(), key);
        return rows.stream().map(row -> view(row, true)).toList();
    }

    @Transactional
    public Map<String, Object> confirm(Actor actor, String raw, String id, DraftRequests.Confirm request) {
        lock(actor, raw);
        var row = owned(actor, id);
        String fingerprint = SessionService.digest(encode(request));
        if (state(row).equals("CONFIRMED") && fingerprint.equals(row.get("confirmation_hash"))) return view(row, true);
        requirePrepared(row, request.version());
        var lines = jdbc.queryForList("SELECT * FROM order_draft_items WHERE draft_id=? ORDER BY medicine_id", id);
        for (var line : lines) {
            Medicine medicine = medicines.selectOne(new QueryWrapper<Medicine>().eq("id", line.get("medicine_id")).last("FOR UPDATE"));
            SalePolicy.require(medicine);
            if (medicine.getStock() < ((Number) line.get("quantity")).intValue()) throw conflict("OUT_OF_STOCK", "商品库存不足");
            if (medicine.getPrice().compareTo((BigDecimal) line.get("price")) != 0) throw conflict("PRICE_CHANGED", "价格已变化，请重新核对并准备草稿");
            if (!Objects.equals(medicine.getQualificationVersion(), ((Number) line.get("qualification_version")).longValue())) {
                throw conflict("QUALIFICATION_CHANGED", "商品审核版本已变化，请重新准备草稿");
            }
        }
        lock(actor, raw);
        jdbc.update("UPDATE order_drafts SET status='CONFIRMED',version=version+1,recipient_name=?,"
                + "recipient_phone=?,recipient_address=?,confirmation_hash=? WHERE id=?",
                request.recipientName().strip(), request.recipientPhone(), request.recipientAddress().strip(), fingerprint, id);
        return view(owned(actor, id), true);
    }

    private void requirePrepared(Map<String, Object> row, long version) {
        if (!state(row).equals("PREPARED")) throw conflict("DRAFT_NOT_PREPARED", "草稿已确认、取消或过期，请刷新");
        if (((Number) row.get("version")).longValue() != version) throw conflict("DRAFT_VERSION_CONFLICT", "草稿版本已变化，请刷新");
    }

    @Transactional
    public Map<String, Object> cancel(Actor actor, String raw, String id, long version) {
        lock(actor, raw);
        var row = owned(actor, id);
        if (state(row).equals("CANCELLED") && (((Number) row.get("version")).longValue() == version
                || ((Number) row.get("version")).longValue() == version + 1)) return view(row, true);
        requirePrepared(row, version);
        jdbc.update("UPDATE order_drafts SET status='CANCELLED',version=version+1 WHERE id=?", id);
        return view(owned(actor, id), true);
    }
}

