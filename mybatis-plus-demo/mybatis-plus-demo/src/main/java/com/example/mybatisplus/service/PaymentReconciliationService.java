package com.example.mybatisplus.service;

import com.example.mybatisplus.security.SessionService;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Fence abandoned requests without initiating or repeating a financial write. */
@Service
public class PaymentReconciliationService {
    private final JdbcTemplate db;
    private final SessionService sessions;
    private final TransactionTemplate tx;
    private final boolean enabled;
    private static final long STALE_SECONDS = 120;
    public PaymentReconciliationService(JdbcTemplate db, SessionService sessions,
            PlatformTransactionManager manager, @Value("${payments.enabled:false}") boolean enabled) {
        this.db = db; this.sessions = sessions; this.enabled = enabled;
        tx = new TransactionTemplate(manager); tx.setTimeout(30);
    }
    public int reconcile() {
        if (!enabled) return 0;
        int changed = 0;
        var candidates = db.queryForList("SELECT user_id,request_key FROM payment_operation_requests WHERE operation='PAY' AND status='REGISTERED' AND created_at<=? ORDER BY created_at,user_id,request_key LIMIT 50",sessions.now()-STALE_SECONDS);
        for (var row : candidates) changed += tx.execute(status -> resolve((String)row.get("user_id"),(String)row.get("request_key")));
        return changed;
    }
    private int resolve(String user, String key) {
        if (db.queryForList("SELECT id FROM users WHERE id=? FOR UPDATE",user).isEmpty()) return 0;
        var requests = db.queryForList("SELECT * FROM payment_operation_requests WHERE user_id=? AND operation='PAY' AND request_key=? FOR UPDATE",user,key);
        if (requests.isEmpty()) return 0;
        var request = requests.getFirst();
        if (!"REGISTERED".equals(request.get("status")) || ((Number)request.get("created_at")).longValue()>sessions.now()-STALE_SECONDS) return 0;
        var orders = db.queryForList("SELECT * FROM orders WHERE id=? AND user_id=? FOR UPDATE",request.get("target_id"),user);
        if (orders.isEmpty()) return reject(user,key,"ORDER_NOT_FOUND");
        Map<String,Object> order = orders.getFirst();
        String id = (String)order.get("id");
        if ("PAID".equals(order.get("payment_status"))) {
            if (db.queryForObject("SELECT COUNT(*) FROM payment_records WHERE order_id=? AND user_id=?",Long.class,id,user)!=1) throw new IllegalStateException("Paid order lacks unique payment audit");
            db.update("UPDATE payment_operation_requests SET status='SUCCEEDED',order_id=?,rejection_code=NULL WHERE user_id=? AND operation='PAY' AND request_key=?",id,user,key);
            return 1;
        }
        db.update("UPDATE payment_authorizations SET status='REVOKED',revoked_at=? WHERE user_id=? AND order_id=? AND status='ACTIVE'",sessions.now(),user,id);
        if (order.get("payment_status")==null) return reject(user,key,"LEGACY_ORDER_UNVERIFIED");
        if ("PENDING_PAYMENT".equals(order.get("payment_status")) && ((Number)order.get("payment_expires_at")).longValue()<=sessions.now()) {
            db.update("UPDATE orders SET payment_status='CLOSED',status='cancelled',payment_version=payment_version+1,closed_at=?,close_reason='EXPIRED' WHERE id=?",sessions.now(),id);
            return reject(user,key,"ORDER_EXPIRED");
        }
        if ("CLOSED".equals(order.get("payment_status"))) return reject(user,key,"EXPIRED".equals(order.get("close_reason")) ? "ORDER_EXPIRED" : "ORDER_CLOSED");
        // Pay takes these same user/request locks and checks REJECTED before debit.
        // Running pay must finish first; queued late pay is fenced by this committed decision.
        return reject(user,key,"PAYMENT_ATTEMPT_EXPIRED");
    }
    private int reject(String user, String key, String code) {
        return db.update("UPDATE payment_operation_requests SET status='REJECTED',rejection_code=? WHERE user_id=? AND operation='PAY' AND request_key=?",code,user,key);
    }
}
