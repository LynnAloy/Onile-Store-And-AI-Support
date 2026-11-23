package com.example.mybatisplus.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.example.mybatisplus.entity.Medicine;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.exception.PaymentException;
import com.example.mybatisplus.mapper.MedicineMapper;
import com.example.mybatisplus.security.Actor;
import com.example.mybatisplus.security.CredentialVerifier;
import com.example.mybatisplus.security.SessionService;
import java.math.BigDecimal;
import java.security.SecureRandom;
import java.util.*;
import java.util.function.Function;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class PaymentService {
    private final JdbcTemplate db;
    private final SessionService sessions;
    private final CredentialVerifier verifier;
    private final MedicineMapper medicines;
    private final TransactionTemplate tx;
    private final PaymentHooks hooks;
    private final boolean enabled;
    private final SecureRandom random = new SecureRandom();
    private static final BigDecimal MAX = new BigDecimal("99999999.99");
    private record Result(Map<String,Object> value, PaymentException error) {}

    public PaymentService(JdbcTemplate db, SessionService sessions, CredentialVerifier verifier,
            MedicineMapper medicines, PlatformTransactionManager manager, PaymentHooks hooks,
            @Value("${payments.enabled:false}") boolean enabled) {
        this.db = db; this.sessions = sessions; this.verifier = verifier; this.medicines = medicines;
        this.tx = new TransactionTemplate(manager); this.hooks = hooks; this.enabled = enabled;
        this.tx.setTimeout(30);
    }
    public boolean enabled() { return enabled; }
    private PaymentException fault(String code) {
        int status = switch (code) {
            case "UNAUTHORIZED", "PAYMENT_AUTHORIZATION_INVALID", "PAYMENT_VERIFICATION_FAILED" -> 401;
            case "FORBIDDEN" -> 403;
            case "ORDER_NOT_FOUND", "DRAFT_NOT_FOUND", "PAYMENT_REQUEST_NOT_FOUND" -> 404;
            case "INVALID_REQUEST", "AMOUNT_OUT_OF_RANGE" -> 400;
            case "INSUFFICIENT_BALANCE", "POINTS_LIMIT" -> 422;
            case "RATE_LIMITED" -> 429;
            case "PAYMENTS_DISABLED" -> 503;
            default -> 409;
        };
        String message = switch (code) {
            case "PAYMENTS_DISABLED" -> "支付功能尚未启用";
            case "PAYMENT_AUTHORIZATION_INVALID" -> "支付授权已失效或绑定不符，请独立重新验证";
            case "PRICE_CHANGED" -> "商品价格已变化，请重新准备草稿";
            case "QUALIFICATION_CHANGED", "SALE_NOT_ALLOWED" -> "商品销售资格或审核版本已变化";
            case "OUT_OF_STOCK" -> "商品库存不足";
            case "INSUFFICIENT_BALANCE" -> "演示钱包余额不足";
            case "ORDER_EXPIRED" -> "待支付订单已过期";
            case "ORDER_CLOSED" -> "订单已关闭";
            case "ORDER_ALREADY_PAID" -> "订单已付款，不能关闭";
            case "LEGACY_ORDER_UNVERIFIED" -> "历史订单未接入新支付验证流程";
            case "IDEMPOTENCY_CONFLICT" -> "相同请求键不能用于不同请求";
            case "ORDER_VERSION_CONFLICT" -> "订单版本已变化，请重新核对";
            case "DRAFT_EXPIRED" -> "草稿转换期限已过，请重新准备";
            case "DRAFT_NOT_CONFIRMED" -> "请先独立确认草稿资料";
            case "ORDER_NOT_FOUND", "DRAFT_NOT_FOUND", "PAYMENT_REQUEST_NOT_FOUND" -> "记录不存在";
            default -> "请求无法执行：" + code;
        };
        return new PaymentException(status, code, message, "NOT_APPLIED");
    }
    private Result ok(Map<String,Object> value) { return new Result(value, null); }
    private Result no(String code) { return new Result(null, fault(code)); }
    private Map<String,Object> finish(Result result) {
        if (result.error != null) throw result.error;
        return result.value;
    }
    private void available() { if (!enabled) throw fault("PAYMENTS_DISABLED"); }
    private void identity(Actor actor, String raw) {
        Actor fresh = sessions.resolve(raw);
        if (fresh == null || !fresh.id().equals(actor.id()) || !fresh.sessionHash().equals(actor.sessionHash())) throw fault("UNAUTHORIZED");
        if (!fresh.scope().equals("USER")) throw fault("FORBIDDEN");
    }
    private Result locked(Actor actor, String raw, Function<Map<String,Object>,Result> action) {
        available();
        return tx.execute(state -> {
            var user = db.queryForMap("SELECT * FROM users WHERE id=? FOR UPDATE", actor.id());
            identity(actor, raw);
            Result result = action.apply(user);
            identity(actor, raw);
            return result;
        });
    }
    private Map<String,Object> owned(Actor actor, String id, boolean draft) {
        String table = draft ? "order_drafts" : "orders";
        var rows = db.queryForList("SELECT * FROM " + table + " WHERE id=? AND user_id=? FOR UPDATE", id, actor.id());
        if (rows.isEmpty()) throw fault(draft ? "DRAFT_NOT_FOUND" : "ORDER_NOT_FOUND");
        return rows.getFirst();
    }
    private long number(Map<String,Object> row, String key) { return ((Number) row.get(key)).longValue(); }
    private String money(Object value) { return ((BigDecimal) value).setScale(2).toPlainString(); }
    private boolean pending(Map<String,Object> order) { return "PENDING_PAYMENT".equals(order.get("payment_status")); }
    private boolean legacy(Map<String,Object> order) { return order.get("payment_status") == null; }
    private boolean walletActive(Map<String,Object> user) {
        Object value = user.get("wallet_activated");
        return Boolean.TRUE.equals(value) || value instanceof Number n && n.intValue()==1;
    }
    private void revokeRows(String user, String order, String authorizationId) {
        String sql = "UPDATE payment_authorizations SET status='REVOKED',revoked_at=? WHERE user_id=? AND order_id=? AND status='ACTIVE'";
        if (authorizationId == null) db.update(sql, sessions.now(), user, order);
        else db.update(sql + " AND id=?", sessions.now(), user, order, authorizationId);
    }
    private void closeRow(Map<String,Object> order, String reason) {
        if (!pending(order)) return;
        long now = sessions.now();
        db.update("UPDATE orders SET payment_status='CLOSED',status='cancelled',payment_version=payment_version+1,closed_at=?,close_reason=? WHERE id=?",
                now, reason, order.get("id"));
        order.put("payment_status", "CLOSED"); order.put("status", "cancelled");
        order.put("payment_version", number(order,"payment_version")+1); order.put("closed_at",now); order.put("close_reason",reason);
        revokeRows((String) order.get("user_id"), (String) order.get("id"), null);
    }
    private String stateError(Map<String,Object> order) {
        if (legacy(order)) return "LEGACY_ORDER_UNVERIFIED";
        if (pending(order) && number(order,"payment_expires_at") <= sessions.now()) closeRow(order,"EXPIRED");
        if ("CLOSED".equals(order.get("payment_status"))) return "EXPIRED".equals(order.get("close_reason")) ? "ORDER_EXPIRED" : "ORDER_CLOSED";
        return null;
    }
    private List<Map<String,Object>> lines(String id, boolean draft) {
        return db.queryForList(draft ? "SELECT * FROM order_draft_items WHERE draft_id=? ORDER BY medicine_id"
                : "SELECT * FROM order_items WHERE order_id=? ORDER BY medicine_id", id);
    }
    private String catalog(List<Map<String,Object>> lines, BigDecimal total) {
        if (lines.isEmpty() || lines.size()>10) return "INVALID_REQUEST";
        BigDecimal sum = BigDecimal.ZERO;
        for (var line : lines) {
            int qty = ((Number) line.get("quantity")).intValue();
            if (qty<1 || qty>99 || line.get("qualification_version")==null) return "INVALID_REQUEST";
            Object name = line.containsKey("name_snapshot") ? line.get("name_snapshot") : line.get("name");
            if (!(name instanceof String text) || text.isBlank() || text.length()>100) return "INVALID_REQUEST";
            Medicine item = medicines.selectOne(new QueryWrapper<Medicine>().eq("id",line.get("medicine_id")).last("FOR UPDATE"));
            if (item==null || SalePolicy.reason(item)!=null) return "SALE_NOT_ALLOWED";
            if (!Objects.equals(item.getQualificationVersion(), number(line,"qualification_version"))) return "QUALIFICATION_CHANGED";
            if (item.getPrice().compareTo((BigDecimal) line.get("price"))!=0) return "PRICE_CHANGED";
            if (item.getStock()<qty) return "OUT_OF_STOCK";
            sum = sum.add(item.getPrice().multiply(BigDecimal.valueOf(qty)));
        }
        return sum.signum()<=0 || sum.compareTo(MAX)>0 || sum.compareTo(total)!=0 ? "AMOUNT_OUT_OF_RANGE" : null;
    }
    private void register(Actor actor, String raw, String operation, String target, long version, String key) {
        if (key==null || !key.matches("[A-Za-z0-9_-]{8,64}")) throw fault("INVALID_REQUEST");
        String hash = SessionService.digest(operation + "|" + target + "|" + version);
        finish(locked(actor,raw,user -> {
            // Ownership checked before durable request registration, but without locking the target first.
            String table = operation.equals("CHECKOUT") ? "order_drafts" : "orders";
            if (db.queryForList("SELECT id FROM " + table + " WHERE id=? AND user_id=?",target,actor.id()).isEmpty())
                return no(operation.equals("CHECKOUT") ? "DRAFT_NOT_FOUND" : "ORDER_NOT_FOUND");
            var rows = db.queryForList("SELECT request_hash FROM payment_operation_requests WHERE user_id=? AND operation=? AND request_key=? FOR UPDATE",actor.id(),operation,key);
            if (!rows.isEmpty()) return hash.equals(rows.getFirst().get("request_hash")) ? ok(Map.of()) : no("IDEMPOTENCY_CONFLICT");
            db.update("INSERT INTO payment_operation_requests(user_id,operation,request_key,request_hash,target_id,status,created_at) VALUES (?,?,?,?,?,'REGISTERED',?)",
                    actor.id(),operation,key,hash,target,sessions.now());
            return ok(Map.of());
        }));
    }
    private Map<String,Object> request(Actor actor, String operation, String key) {
        return db.queryForMap("SELECT * FROM payment_operation_requests WHERE user_id=? AND operation=? AND request_key=? FOR UPDATE",actor.id(),operation,key);
    }
    private Result reject(Actor actor, String operation, String key, Map<String,Object> order, String code) {
        if (order != null && !legacy(order)) {
            revokeRows(actor.id(),(String)order.get("id"),null);
            if (Set.of("PRICE_CHANGED","SALE_NOT_ALLOWED","QUALIFICATION_CHANGED").contains(code)) closeRow(order,"CATALOG_CHANGED");
        }
        db.update("UPDATE payment_operation_requests SET status='REJECTED',rejection_code=? WHERE user_id=? AND operation=? AND request_key=?",
                code,actor.id(),operation,key);
        return no(code);
    }
    private void success(Actor actor, String operation, String key, String order) {
        db.update("UPDATE payment_operation_requests SET status='SUCCEEDED',order_id=?,rejection_code=NULL WHERE user_id=? AND operation=? AND request_key=?",order,actor.id(),operation,key);
    }
    public Map<String,Object> checkout(Actor actor, String raw, String draftId, long version, String key) {
        register(actor,raw,"CHECKOUT",draftId,version,key);
        return finish(locked(actor,raw,user -> {
            var req = request(actor,"CHECKOUT",key);
            if ("REJECTED".equals(req.get("status"))) return no((String)req.get("rejection_code"));
            var draft = owned(actor,draftId,true);
            var prior = db.queryForList("SELECT * FROM orders WHERE source_draft_id=? AND user_id=? FOR UPDATE",draftId,actor.id());
            if (!prior.isEmpty()) {
                success(actor,"CHECKOUT",key,(String)prior.getFirst().get("id"));
                stateError(prior.getFirst());
                return ok(view(prior.getFirst()));
            }
            String error = !"CONFIRMED".equals(draft.get("status")) ? "DRAFT_NOT_CONFIRMED"
                    : number(draft,"version")!=version ? "ORDER_VERSION_CONFLICT"
                    : number(draft,"expires_at")<=sessions.now() ? "DRAFT_EXPIRED" : null;
            var items = lines(draftId,true);
            if (error==null) error = catalog(items,(BigDecimal)draft.get("total_price"));
            if (error!=null) return reject(actor,"CHECKOUT",key,null,error);
            identity(actor,raw);
            if (number(draft,"expires_at")<=sessions.now()) return reject(actor,"CHECKOUT",key,null,"DRAFT_EXPIRED");
            String id = OrderService.newId("ORD_");
            db.update("INSERT INTO orders(id,user_id,total_price,status,recipient_name,recipient_phone,recipient_address,source_draft_id,payment_status,payment_version,payment_expires_at) "
                    + "VALUES (?,?,?,'pending',?,?,?,?,'PENDING_PAYMENT',1,?)",id,actor.id(),draft.get("total_price"),
                    draft.get("recipient_name"),draft.get("recipient_phone"),draft.get("recipient_address"),draftId,sessions.now()+900);
            for (var item : items) db.update("INSERT INTO order_items(order_id,medicine_id,quantity,price,name_snapshot,qualification_version) VALUES (?,?,?,?,?,?)",
                    id,item.get("medicine_id"),item.get("quantity"),item.get("price"),item.get("name"),item.get("qualification_version"));
            success(actor,"CHECKOUT",key,id);
            return ok(view(owned(actor,id,false)));
        }));
    }
    public Map<String,Object> read(Actor actor, String raw, String id, String key) {
        return finish(locked(actor,raw,user -> {
            var order = owned(actor,id,false);
            Map<String,Object> outcome = null;
            if (key!=null) {
                if (!key.matches("[A-Za-z0-9_-]{8,64}")) return no("INVALID_REQUEST");
                var rows = db.queryForList("SELECT status,rejection_code FROM payment_operation_requests WHERE user_id=? AND operation='PAY' AND request_key=? AND target_id=?",actor.id(),key,id);
                if (rows.isEmpty()) return no("PAYMENT_REQUEST_NOT_FOUND");
                outcome = new LinkedHashMap<>(); outcome.put("requestKey",key); outcome.put("status",rows.getFirst().get("status")); outcome.put("code",rows.getFirst().get("rejection_code"));
            }
            stateError(order);
            var result = view(order);
            if (outcome!=null) result.put("requestOutcome",outcome);
            return ok(result);
        }));
    }
    private Result ready(Actor actor, Map<String,Object> order, long version) {
        String error = stateError(order);
        if (error==null && !pending(order)) error = "ORDER_ALREADY_PAID";
        if (error==null && number(order,"payment_version")!=version) error = "ORDER_VERSION_CONFLICT";
        if (error==null) db.queryForList("SELECT id FROM payment_authorizations WHERE user_id=? AND order_id=? ORDER BY id FOR UPDATE",actor.id(),order.get("id"));
        if (error==null) error = catalog(lines((String)order.get("id"),false),(BigDecimal)order.get("total_price"));
        if (error!=null) {
            if (!legacy(order)) revokeRows(actor.id(),(String)order.get("id"),null);
            if (Set.of("PRICE_CHANGED","QUALIFICATION_CHANGED","SALE_NOT_ALLOWED").contains(error)) closeRow(order,"CATALOG_CHANGED");
            return no(error);
        }
        return ok(Map.of());
    }
    public Map<String,Object> authorize(Actor actor, String raw, String id, long version, String password) {
        if (password==null || password.getBytes(java.nio.charset.StandardCharsets.UTF_8).length>72) throw fault("INVALID_REQUEST");
        finish(locked(actor,raw,user -> ready(actor,owned(actor,id,false),version)));
        try { verifier.verify(actor.username(),password,true); }
        catch (ApiException ex) { throw new PaymentException(ex.getStatus().value(),ex.getCode(),ex.getMessage(),"NOT_APPLIED"); }
        return finish(locked(actor,raw,user -> {
            var order = owned(actor,id,false);
            var readiness = ready(actor,order,version);
            if (readiness.error!=null) return readiness;
            if (!walletActive(user)) return no("PAYMENT_VERIFICATION_FAILED");
            identity(actor,raw);
            long parent = db.queryForObject("SELECT expires_at FROM auth_sessions WHERE token_hash=?",Long.class,actor.sessionHash());
            long now = sessions.now();
            long expires = Math.min(now+60,Math.min(parent,number(order,"payment_expires_at")));
            if (number(order,"payment_expires_at")<=now) { closeRow(order,"EXPIRED"); return no("ORDER_EXPIRED"); }
            if (expires<=now) return no("UNAUTHORIZED");
            byte[] bytes = new byte[32]; random.nextBytes(bytes);
            String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
            String aid = UUID.randomUUID().toString();
            revokeRows(actor.id(),id,null);
            db.update("INSERT INTO payment_authorizations(id,token_hash,user_id,parent_hash,order_id,order_version,amount,currency,status,created_at,expires_at) VALUES (?,?,?,?,?,?,?,'CNY','ACTIVE',?,?)",
                    aid,SessionService.digest(token),actor.id(),actor.sessionHash(),id,version,order.get("total_price"),now,expires);
            return ok(Map.of("authorizationId",aid,"token",token,"orderId",id,"orderVersion",version,"amount",money(order.get("total_price")),"currency","CNY","expiresAt",expires));
        }));
    }
    public Map<String,Object> revoke(Actor actor, String raw, String id, String authorizationId) {
        if (authorizationId!=null && !authorizationId.matches("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")) throw fault("INVALID_REQUEST");
        return finish(locked(actor,raw,user -> {
            var order = owned(actor,id,false); stateError(order);
            revokeRows(actor.id(),id,authorizationId);
            return ok(Map.of("revoked",true));
        }));
    }
    public Map<String,Object> close(Actor actor, String raw, String id, long version) {
        return finish(locked(actor,raw,user -> {
            var order = owned(actor,id,false); String error = stateError(order);
            if (legacy(order)) return no(error);
            if ("PAID".equals(order.get("payment_status"))) return no("ORDER_ALREADY_PAID");
            if (!pending(order)) return ok(view(order));
            if (number(order,"payment_version")!=version) { revokeRows(actor.id(),id,null); return no("ORDER_VERSION_CONFLICT"); }
            identity(actor,raw); closeRow(order,"USER_CANCELLED"); return ok(view(order));
        }));
    }
    public Map<String,Object> pay(Actor actor, String raw, String id, long version, String key, String token) {
        if (token==null || !token.matches("[A-Za-z0-9_-]{43}")) throw fault("PAYMENT_AUTHORIZATION_INVALID");
        try { register(actor,raw,"PAY",id,version,key); }
        catch (PaymentException ex) { throw ex; }
        catch (RuntimeException ex) {
            throw new PaymentException(503,"TRANSACTION_RETRYABLE","付款尚未开始，请保留原请求键核对","NOT_APPLIED");
        }
        final boolean[] callbackFailed = {false};
        try {
            return finish(locked(actor,raw,user -> {
                try { return settle(actor,raw,user,id,version,key,token); }
                catch (RuntimeException ex) { callbackFailed[0] = true; throw ex; }
            }));
        } catch (PaymentException ex) { throw ex; }
        catch (RuntimeException ex) {
            boolean rolledBack = callbackFailed[0] && !(ex instanceof TransactionException);
            throw new PaymentException(503, rolledBack ? "TRANSACTION_RETRYABLE" : "PAYMENT_OUTCOME_UNKNOWN",
                    "付款结果请通过本人订单核对，不要更换请求键再次付款",rolledBack ? "NOT_APPLIED" : "UNKNOWN");
        }
    }
    private Result settle(Actor actor, String raw, Map<String,Object> user, String id, long version, String key, String token) {
        var req = request(actor,"PAY",key);
        var order = owned(actor,id,false);
        if ("REJECTED".equals(req.get("status"))) return no((String)req.get("rejection_code"));
        if ("PAID".equals(order.get("payment_status"))) { success(actor,"PAY",key,id); return ok(receipt(id)); }
        String error = stateError(order);
        if (error!=null) return reject(actor,"PAY",key,order,error);
        if (number(order,"payment_version")!=version) return reject(actor,"PAY",key,order,"ORDER_VERSION_CONFLICT");
        var grants = db.queryForList("SELECT * FROM payment_authorizations WHERE token_hash=? AND user_id=? AND order_id=? FOR UPDATE",SessionService.digest(token),actor.id(),id);
        if (grants.isEmpty()) return reject(actor,"PAY",key,null,"PAYMENT_AUTHORIZATION_INVALID");
        var grant = grants.getFirst();
        if (!"ACTIVE".equals(grant.get("status")) || !actor.sessionHash().equals(grant.get("parent_hash"))
                || number(grant,"expires_at")<=sessions.now() || number(grant,"order_version")!=version
                || ((BigDecimal)grant.get("amount")).compareTo((BigDecimal)order.get("total_price"))!=0
                || !"CNY".equals(grant.get("currency"))) {
            revokeRows(actor.id(),id,(String)grant.get("id"));
            return reject(actor,"PAY",key,null,"PAYMENT_AUTHORIZATION_INVALID");
        }
        if (!walletActive(user)) return reject(actor,"PAY",key,order,"PAYMENT_VERIFICATION_FAILED");
        var items = lines(id,false);
        error = catalog(items,(BigDecimal)order.get("total_price"));
        if (error!=null) return reject(actor,"PAY",key,order,error);
        BigDecimal amount = (BigDecimal) order.get("total_price");
        if (((BigDecimal)user.get("balance")).compareTo(amount)<0) return reject(actor,"PAY",key,order,"INSUFFICIENT_BALANCE");
        long points = number(user,"points") + amount.longValue();
        if (points>Integer.MAX_VALUE) return reject(actor,"PAY",key,order,"POINTS_LIMIT");
        identity(actor,raw);
        if (number(order,"payment_expires_at")<=sessions.now()) { closeRow(order,"EXPIRED"); return reject(actor,"PAY",key,order,"ORDER_EXPIRED"); }
        if (number(grant,"expires_at")<=sessions.now()) return reject(actor,"PAY",key,null,"PAYMENT_AUTHORIZATION_INVALID");
        long authorizedAt = sessions.now();
        if (authorizedAt>=number(grant,"expires_at")) return reject(actor,"PAY",key,null,"PAYMENT_AUTHORIZATION_INVALID");
        commitSettlement(actor.id(),user,id,amount,items,(String)grant.get("id"),authorizedAt);
        success(actor,"PAY",key,id);
        return ok(receipt(id));
    }
    // Both consent paths use the same financial transaction; caller holds user and product locks.
    void commitSettlement(String userId, Map<String,Object> user, String id, BigDecimal amount,
            List<Map<String,Object>> items, String authorizationId, long authorizedAt) {
        if (!org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive())
            throw new IllegalStateException("Settlement requires a transaction");
        long points=number(user,"points")+amount.longValue();
        if (((BigDecimal)user.get("balance")).compareTo(amount)<0 || points>Integer.MAX_VALUE)
            throw new IllegalStateException("Settlement preconditions failed");
        if (db.update("UPDATE users SET balance=balance-?,points=? WHERE id=? AND balance>=?",amount,points,userId,amount)!=1) throw new IllegalStateException("Debit failed");
        for (var item : items) if (db.update("UPDATE medicines SET stock=stock-? WHERE id=? AND stock>=?",item.get("quantity"),item.get("medicine_id"),item.get("quantity"))!=1) throw new IllegalStateException("Stock write failed");
        hooks.afterDebit(id);
        String ledger=OrderService.newId("TX_"); String payment=OrderService.newId("PAY_");
        long now=authorizedAt;
        db.update("INSERT INTO transactions(id,user_id,type,amount,points_change,related_id) VALUES (?,?,'purchase',?,?,?)",ledger,userId,amount.negate(),amount.intValue(),id);
        db.update("INSERT INTO payment_records(id,order_id,user_id,authorization_id,ledger_id,amount,currency,paid_at) VALUES (?,?,?,?,?,?,'CNY',?)",payment,id,userId,authorizationId,ledger,amount,now);
        db.update("UPDATE orders SET status='completed',payment_status='PAID',payment_version=payment_version+1,paid_at=? WHERE id=?",now,id);
        db.update("UPDATE payment_authorizations SET status='CONSUMED',consumed_at=? WHERE id=?",authorizedAt,authorizationId);
    }
    Map<String,Object> receipt(String id) {
        var row = db.queryForMap("SELECT * FROM payment_records WHERE order_id=?",id);
        return Map.of("paymentId",row.get("id"),"orderId",id,"amount",money(row.get("amount")),"currency","CNY","paidAt",row.get("paid_at"),"ledgerId",row.get("ledger_id"));
    }
    private Map<String,Object> view(Map<String,Object> order) {
        var result = new LinkedHashMap<String,Object>();
        for (String key : List.of("id","status","note")) result.put(key,order.get(key));
        result.put("orderId",order.get("id")); result.put("userId",order.get("user_id"));
        Object created = order.get("created_at");
        result.put("createdAt",created instanceof java.sql.Timestamp t ? t.toInstant().toString()
                : created instanceof java.time.LocalDateTime t ? t.atZone(java.time.ZoneId.of("Asia/Hong_Kong")).toInstant().toString() : created.toString());
        result.put("sourceDraftId",order.get("source_draft_id")); result.put("paymentStatus",legacy(order)?"LEGACY_UNVERIFIED":order.get("payment_status"));
        result.put("version",order.get("payment_version")); result.put("totalPrice",money(order.get("total_price"))); result.put("currency","CNY");
        result.put("expiresAt",order.get("payment_expires_at")); result.put("closeReason",order.get("close_reason"));
        result.put("recipientName",order.get("recipient_name")); result.put("recipientPhone",order.get("recipient_phone")); result.put("recipientAddress",order.get("recipient_address"));
        var items = new ArrayList<Map<String,Object>>();
        for (var item : lines((String)order.get("id"),false)) {
            var line = new LinkedHashMap<String,Object>();
            line.put("medicineId",item.get("medicine_id")); line.put("quantity",item.get("quantity"));
            line.put("name",item.get("name_snapshot")); line.put("price",money(item.get("price"))); line.put("qualificationVersion",item.get("qualification_version")); items.add(line);
        }
        result.put("items",items);
        if ("PAID".equals(order.get("payment_status"))) result.put("payment",receipt((String)order.get("id")));
        return result;
    }
    @SuppressWarnings("unchecked")
    public List<Map<String,Object>> list(Actor actor, String raw, String phone) {
        return (List<Map<String,Object>>)finish(locked(actor,raw,user -> {
            var ids = phone==null ? db.queryForList("SELECT id FROM orders WHERE user_id=? ORDER BY created_at DESC,id LIMIT 50",actor.id())
                    : db.queryForList("SELECT id FROM orders WHERE user_id=? AND recipient_phone=? ORDER BY created_at DESC,id LIMIT 50",actor.id(),phone);
            List<Map<String,Object>> rows = new ArrayList<>();
            for (var row : ids) { var order = owned(actor,(String)row.get("id"),false); stateError(order); rows.add(view(order)); }
            return ok(Map.of("orders",rows));
        })).get("orders");
    }
    public Map<String,Object> agentSummary(Actor actor, String id) {
        if (!"AGENT_READ".equals(actor.scope())) throw fault("FORBIDDEN");
        var found = db.queryForList("SELECT * FROM orders WHERE id=? AND user_id=?",id,actor.id());
        if (found.isEmpty()) throw fault("ORDER_NOT_FOUND");
        var order = found.getFirst();
        String status = legacy(order) ? "LEGACY_UNVERIFIED" : (String)order.get("payment_status");
        if (pending(order) && number(order,"payment_expires_at")<=sessions.now()) status = "CLOSED";
        var items = new ArrayList<Map<String,Object>>();
        for (var line : lines(id,false)) {
            Object name = line.get("name_snapshot");
            if (name==null) {
                var product = medicines.selectById((java.io.Serializable)line.get("medicine_id"));
                name = product==null ? "历史商品" : product.getName();
            }
            items.add(Map.of("medicineId",line.get("medicine_id"),"name",name,"quantity",line.get("quantity"),"price",money(line.get("price"))));
        }
        return Map.of("orderId",id,"status",status,"totalPrice",money(order.get("total_price")),"currency","CNY","items",items);
    }
}
