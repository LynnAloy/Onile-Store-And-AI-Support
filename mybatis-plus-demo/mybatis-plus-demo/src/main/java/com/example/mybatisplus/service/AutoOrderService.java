package com.example.mybatisplus.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.example.mybatisplus.dto.CommerceRequests;
import com.example.mybatisplus.entity.Medicine;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.exception.PaymentException;
import com.example.mybatisplus.mapper.MedicineMapper;
import com.example.mybatisplus.security.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.time.*;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class AutoOrderService {
    private final JdbcTemplate db;
    private final CommerceAccess access;
    private final SessionService sessions;
    private final CredentialVerifier verifier;
    private final MedicineMapper medicines;
    private final PaymentService payments;
    private final PurchaseRiskService risk;
    private final ObjectMapper json;
    private final TransactionTemplate tx;
    private record Outcome(Map<String,Object> value, ApiException error) {}
    public AutoOrderService(JdbcTemplate db,CommerceAccess access,SessionService sessions,
            CredentialVerifier verifier,MedicineMapper medicines,PaymentService payments,
            ObjectMapper json,PlatformTransactionManager manager,PurchaseRiskService risk) {
        this.db=db; this.access=access; this.sessions=sessions; this.verifier=verifier;
        this.medicines=medicines; this.payments=payments; this.json=json; this.risk=risk;
        this.tx=new TransactionTemplate(manager); this.tx.setTimeout(30);
    }
    private ApiException fail(String code,String message) {
        return new PaymentException(409,code,message,"NOT_APPLIED");
    }
    private Map<String,Object> user(Actor actor,String raw) {
        access.available();
        if (!payments.enabled()) throw fail("PAYMENTS_DISABLED","支付功能尚未启用");
        var user=db.queryForMap("SELECT * FROM users WHERE id=? FOR UPDATE",actor.id());
        access.identity(actor,raw);
        return user;
    }
    private long num(Map<String,Object> row,String key) { return ((Number)row.get(key)).longValue(); }
    private boolean yes(Object value) { return Boolean.TRUE.equals(value) || value instanceof Number n && n.intValue()==1; }
    public static LocalDate budgetDay(long epochSeconds) {
        return Instant.ofEpochSecond(epochSeconds).atOffset(ZoneOffset.ofHours(-8)).toLocalDate();
    }
    private Map<String,Object> policyRow(Actor actor) {
        var rows=db.queryForList("SELECT * FROM auto_order_policies WHERE user_id=? FOR UPDATE",actor.id());
        if (rows.isEmpty()) {
            db.update("INSERT INTO auto_order_policies(user_id,updated_at) VALUES (?,?)",actor.id(),sessions.now());
            return db.queryForMap("SELECT * FROM auto_order_policies WHERE user_id=?",actor.id());
        }
        return rows.getFirst();
    }
    private boolean enabled(Actor actor,Map<String,Object> policy) {
        return yes(policy.get("enabled")) && actor.sessionHash().equals(policy.get("parent_hash"));
    }
    private BigDecimal spent(Actor actor,LocalDate day) {
        return db.queryForObject("SELECT COALESCE(SUM(amount),0) FROM auto_order_turns WHERE user_id=? AND budget_day=? AND status='PAID'",BigDecimal.class,actor.id(),day);
    }
    private Map<String,Object> policyView(Actor actor,Map<String,Object> row) {
        LocalDate day=budgetDay(sessions.now());
        BigDecimal used=spent(actor,day);
        return Map.of("enabled",enabled(actor,row),"perOrderLimit",row.get("per_order_limit"),
                "dailyLimit",row.get("daily_limit"),"version",row.get("version"),"dailySpent",used,
                "dailyRemaining",((BigDecimal)row.get("daily_limit")).subtract(used).max(BigDecimal.ZERO),
                "budgetDay",day.toString(),"timeZone","PST (UTC-08:00)");
    }
    public Map<String,Object> policy(Actor actor,String raw) {
        return tx.execute(status -> { user(actor,raw); return policyView(actor,policyRow(actor)); });
    }
    public Map<String,Object> update(Actor actor,String raw,CommerceRequests.Policy body) {
        if (body.dailyLimit().compareTo(body.perOrderLimit())<0) throw fail("INVALID_LIMITS","每日额度不能低于单笔额度");
        // Verify outside the user lock: the verifier has an independent lockout transaction.
        boolean needsPin=tx.execute(status -> {
            user(actor,raw); var row=policyRow(actor);
            if (num(row,"version")!=body.expectedVersion()) throw fail("VERSION_CONFLICT","授权设置已变化，请刷新");
            return body.enabled() && !enabled(actor,row) || body.perOrderLimit().compareTo((BigDecimal)row.get("per_order_limit"))>0
                    || body.dailyLimit().compareTo((BigDecimal)row.get("daily_limit"))>0;
        });
        if (needsPin) {
            if (body.password()==null || body.password().getBytes(java.nio.charset.StandardCharsets.UTF_8).length>72)
                throw fail("PIN_REQUIRED","开启、重新开启或提高额度需要支付密码");
            verifier.verify(actor.username(),body.password(),true);
        }
        return tx.execute(status -> {
            var user=user(actor,raw); var row=policyRow(actor);
            if (num(row,"version")!=body.expectedVersion()) throw fail("VERSION_CONFLICT","授权设置已变化，请刷新");
            if (body.enabled() && !yes(user.get("wallet_activated"))) throw fail("WALLET_INACTIVE","请先激活演示钱包");
            db.update("UPDATE auto_order_policies SET enabled=?,per_order_limit=?,daily_limit=?,version=version+1,parent_hash=?,updated_at=? WHERE user_id=?",
                    body.enabled(),body.perOrderLimit(),body.dailyLimit(),actor.sessionHash(),sessions.now(),actor.id());
            var after=policyRow(actor);
            try {
                // No PIN or session token is serialized into the audit.
                db.update("INSERT INTO auto_order_policy_audit VALUES (?,?,?,?,?,?)",UUID.randomUUID().toString(),actor.id(),
                        json.writeValueAsString(policyView(actor,row)),json.writeValueAsString(policyView(actor,after)),needsPin,sessions.now());
            } catch (com.fasterxml.jackson.core.JsonProcessingException ex) { throw new IllegalStateException(ex); }
            access.identity(actor,raw);
            return policyView(actor,after);
        });
    }
    public Map<String,Object> register(Actor actor,String raw,CommerceRequests.Turn body) {
        return tx.execute(status -> {
            var user=user(actor,raw); var policy=policyRow(actor);
            var rows=db.queryForList("SELECT * FROM auto_order_turns WHERE user_id=? AND turn_id=? FOR UPDATE",actor.id(),body.turnId());
            if (!rows.isEmpty()) {
                var prior=rows.getFirst();
                if (!SessionService.digest(body.message()).equals(prior.get("message_hash"))
                        || !body.conversationId().equals(prior.get("conversation_id"))) throw fail("IDEMPOTENCY_CONFLICT","本轮请求键已被使用");
                return turnView(prior);
            }
            if (!enabled(actor,policy) || !PurchaseGrounding.requested(body.message())) return Map.of("status","MANUAL");
            if (db.queryForObject("SELECT COUNT(*) FROM auto_order_turns WHERE user_id=? AND status='READY' AND expires_at>?",Integer.class,actor.id(),sessions.now())>=10)
                throw fail("TOO_MANY_TURNS","待处理请求过多，请稍后重试");
            db.update("INSERT INTO auto_order_turns(user_id,turn_id,conversation_id,parent_hash,policy_version,profile_version,message_text,message_hash,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    actor.id(),body.turnId(),body.conversationId(),actor.sessionHash(),policy.get("version"),user.get("profile_context_version"),body.message(),SessionService.digest(body.message()),sessions.now(),sessions.now()+300);
            return Map.of("status","READY","turnId",body.turnId());
        });
    }
    private Map<String,Object> turn(Actor actor,String id) {
        var rows=db.queryForList("SELECT * FROM auto_order_turns WHERE user_id=? AND turn_id=? FOR UPDATE",actor.id(),id);
        if (rows.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND,"TURN_NOT_FOUND","请求记录不存在");
        return rows.getFirst();
    }
    private Map<String,Object> turnView(Map<String,Object> row) {
        var result=new LinkedHashMap<String,Object>();
        result.put("turnId",row.get("turn_id")); result.put("status",row.get("status")); result.put("code",row.get("rejection_code"));
        if ("PAID".equals(row.get("status"))) {
            result.put("orderId",row.get("order_id")); result.put("payment",payments.receipt((String)row.get("order_id")));
        }
        return result;
    }
    public Map<String,Object> read(Actor actor,String raw,String id) {
        return tx.execute(status -> { user(actor,raw); return turnView(turn(actor,id)); });
    }
    public List<Map<String,Object>> history(Actor actor,String raw,String conversation) {
        return tx.execute(status -> {
            user(actor,raw);
            return db.queryForList("SELECT * FROM auto_order_turns WHERE user_id=? AND conversation_id=? ORDER BY created_at DESC LIMIT 50",actor.id(),conversation)
                    .stream().map(this::turnView).toList();
        });
    }
    public Map<String,Object> execute(Actor actor,String raw,String id,CommerceRequests.Execute body) {
        var items=body.items().stream().sorted(Comparator.comparingInt(CommerceRequests.Item::medicineId)).toList();
        if (items.stream().map(CommerceRequests.Item::medicineId).distinct().count()!=items.size()) throw fail("INVALID_REQUEST","商品不能重复");
        String fingerprint=SessionService.digest(items.toString());
        Outcome outcome;
        try {
            outcome=tx.execute(status -> {
                var user=user(actor,raw); var policy=policyRow(actor); var turn=turn(actor,id);
                if (turn.get("request_hash")!=null && !fingerprint.equals(turn.get("request_hash")))
                    throw fail("IDEMPOTENCY_CONFLICT","同一对话轮次不能更改商品或重复下单");
                if (!"READY".equals(turn.get("status"))) return new Outcome(turnView(turn),null);
                db.update("UPDATE auto_order_turns SET request_hash=? WHERE user_id=? AND turn_id=?",fingerprint,actor.id(),id);
                List<Map<String,Object>> lines=new ArrayList<>();
                BigDecimal amount=BigDecimal.ZERO;
                try {
                    if (!enabled(actor,policy) || num(policy,"version")!=num(turn,"policy_version")
                            || !actor.sessionHash().equals(turn.get("parent_hash"))) throw fail("AUTO_AUTH_REVOKED","智能下单授权已撤回或变化");
                    if (num(turn,"expires_at")<=sessions.now()) throw fail("AUTO_TURN_EXPIRED","本轮授权已过期，请重新发起对话");
                    if (num(user,"profile_context_version")!=num(turn,"profile_version")) throw fail("PROFILE_CHANGED","资料已变化，请重新发起对话");
                    for (var requested:items) {
                        Medicine item=medicines.selectOne(new QueryWrapper<Medicine>().eq("id",requested.medicineId()).last("FOR UPDATE"));
                        if (item==null || SalePolicy.reason(item)!=null) throw fail("SALE_NOT_ALLOWED","仅审核通过的非处方商品可以智能下单");
                        if (db.queryForObject("SELECT COUNT(*) FROM medicines WHERE name=?",Integer.class,item.getName())!=1)
                            throw fail("SPECIFICATION_REQUIRED","同名商品存在多个规格，请先手动核对");
                        if (item.getStock()<requested.quantity()) throw fail("OUT_OF_STOCK","商品库存不足");
                        lines.add(Map.of("medicine_id",item.getId(),"medicineId",item.getId(),"name",item.getName(),"quantity",requested.quantity(),"price",item.getPrice(),"qualification_version",item.getQualificationVersion()));
                        amount=amount.add(item.getPrice().multiply(BigDecimal.valueOf(requested.quantity())));
                    }
                    if (!PurchaseGrounding.exact((String)turn.get("message_text"),lines)) throw fail("EXPLICIT_PURCHASE_REQUIRED","请明确完整商品名称和数量，例如：帮我下单2件商品名称；本次未扣款");
                    String riskReason=risk.reason(user,lines);
                    if (riskReason!=null) throw fail("HEALTH_REVIEW_REQUIRED",riskReason);
                    if (!yes(user.get("wallet_activated"))) throw fail("WALLET_INACTIVE","钱包尚未激活");
                    for (String key:List.of("name","phone_num","address")) {
                        Object value=user.get(key);
                        if (!(value instanceof String text) || text.isBlank()) throw fail("SHIPPING_REQUIRED","请先完善个人资料中的收货人、手机号和地址");
                    }
                    if (!user.get("phone_num").toString().matches("1[3-9][0-9]{9}")) throw fail("SHIPPING_REQUIRED","请填写有效的收货手机号");
                    if (user.get("name").toString().length()>15 || user.get("address").toString().length()>50)
                        throw fail("SHIPPING_REQUIRED","收货资料长度不合法");
                    if (amount.signum()<=0 || amount.compareTo((BigDecimal)policy.get("per_order_limit"))>0) throw fail("PER_ORDER_LIMIT","超过智能下单单笔额度");
                    if (spent(actor,budgetDay(sessions.now())).add(amount).compareTo((BigDecimal)policy.get("daily_limit"))>0) throw fail("DAILY_LIMIT","超过 PST 当日累计额度");
                    if (((BigDecimal)user.get("balance")).compareTo(amount)<0) throw fail("INSUFFICIENT_BALANCE","演示钱包余额不足");
                    if (num(user,"points")+amount.longValue()>Integer.MAX_VALUE) throw fail("POINTS_LIMIT","积分已达上限");
                    access.identity(actor,raw);
                    if (num(turn,"expires_at")<=sessions.now()) throw fail("AUTO_TURN_EXPIRED","本轮授权已过期");
                } catch (ApiException ex) {
                    db.update("UPDATE auto_order_turns SET status='REJECTED',rejection_code=? WHERE user_id=? AND turn_id=?",ex.getCode(),actor.id(),id);
                    return new Outcome(null,ex);
                }
                // No financial write occurs before all checks have passed. Shared settlement below is atomic.
                long now=sessions.now();
                if (spent(actor,budgetDay(now)).add(amount).compareTo((BigDecimal)policy.get("daily_limit"))>0) {
                    db.update("UPDATE auto_order_turns SET status='REJECTED',rejection_code='DAILY_LIMIT' WHERE user_id=? AND turn_id=?",actor.id(),id);
                    return new Outcome(null,fail("DAILY_LIMIT","超过 PST 当日累计额度"));
                }
                String draft=UUID.randomUUID().toString(), order=OrderService.newId("ORD_"), grant=UUID.randomUUID().toString();
                db.update("INSERT INTO order_drafts(id,user_id,grant_hash,request_key,request_hash,status,version,total_price,created_at,expires_at,recipient_name,recipient_phone,recipient_address) VALUES (?,?,?,?,?,'CONFIRMED',1,?,?,?,?,?,?)",
                        draft,actor.id(),SessionService.digest("auto:"+id),id,fingerprint,amount,now,now+900,user.get("name"),user.get("phone_num"),user.get("address"));
                db.update("INSERT INTO orders(id,user_id,total_price,status,recipient_name,recipient_phone,recipient_address,source_draft_id,payment_status,payment_version,payment_expires_at) VALUES (?,?,?,'pending',?,?,?,?,'PENDING_PAYMENT',1,?)",
                        order,actor.id(),amount,user.get("name"),user.get("phone_num"),user.get("address"),draft,now+60);
                for (var line:lines) {
                    db.update("INSERT INTO order_draft_items(draft_id,medicine_id,name,quantity,price,qualification_version) VALUES (?,?,?,?,?,?)",draft,line.get("medicine_id"),line.get("name"),line.get("quantity"),line.get("price"),line.get("qualification_version"));
                    db.update("INSERT INTO order_items(order_id,medicine_id,quantity,price,name_snapshot,qualification_version) VALUES (?,?,?,?,?,?)",order,line.get("medicine_id"),line.get("quantity"),line.get("price"),line.get("name"),line.get("qualification_version"));
                }
                db.update("INSERT INTO payment_authorizations(id,token_hash,user_id,parent_hash,order_id,order_version,amount,currency,status,created_at,expires_at) VALUES (?,?,?,?,?,1,?,'CNY','ACTIVE',?,?)",
                        grant,SessionService.digest(UUID.randomUUID().toString()),actor.id(),actor.sessionHash(),order,amount,now,now+60);
                payments.commitSettlement(actor.id(),user,order,amount,lines,grant,now);
                db.update("UPDATE auto_order_turns SET status='PAID',order_id=?,amount=?,budget_day=? WHERE user_id=? AND turn_id=?",order,amount,budgetDay(now),actor.id(),id);
                access.identity(actor,raw);
                return new Outcome(turnView(turn(actor,id)),null);
            });
        } catch (ApiException ex) { throw ex; }
        catch (RuntimeException ex) {
            throw new PaymentException(503,"AUTO_ORDER_OUTCOME_UNKNOWN","请查询本轮下单结果，勿更换请求键重复下单","UNKNOWN");
        }
        if (outcome.error()!=null) throw outcome.error();
        return outcome.value();
    }
}
