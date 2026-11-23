package com.example.mybatisplus;

import com.example.mybatisplus.security.SessionService;
import com.example.mybatisplus.service.PaymentHooks;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.SpyBean;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.mockito.Mockito.*;

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@TestPropertySource(properties={"payments.enabled=true",
    "payments.recovery-scheduling-enabled=false",
    "spring.datasource.url=jdbc:h2:mem:m51;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1",
    "spring.sql.init.schema-locations=classpath:sql/test-schema.sql,classpath:sql/m1-security-tables.sql,classpath:sql/m3-profile-schema.sql,classpath:sql/m4-draft-schema.sql,classpath:sql/m51-test-schema.sql"})
class PaymentBusinessTests {
    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate db;
    @Autowired ObjectMapper json;
    @Autowired SessionService sessions;
    @Autowired PasswordEncoder encoder;
    @Autowired com.example.mybatisplus.service.PaymentReconciliationService recovery;
    @SpyBean PaymentHooks hooks;
    String pin;
    String a;
    String b;
    @BeforeAll void hashes() { pin=encoder.encode("123456"); }
    @BeforeEach void reset() {
        org.mockito.Mockito.reset(hooks);
        for (String table : List.of("payment_records","payment_operation_requests","payment_authorizations",
                "order_items","transactions","checkout_requests","orders","order_draft_items","order_drafts",
                "order_agent_grants","profile_consent_events","auth_sessions","security_attempts","recharge_cards","medicines","users")) db.update("DELETE FROM "+table);
        for (String name : List.of("alice","bob")) db.update("INSERT INTO users(id,user_id,password,balance,points,wallet_activated,walletPassword) VALUES (?,?,?,100,0,TRUE,?)",name+"-id",name,pin,pin);
        db.update("INSERT INTO medicines(id,name,price,stock,sale_classification,review_status,reference_source,reviewed_by,qualification_version) VALUES (1,'虚构支付测试',10.80,10,'OTC','APPROVED','local://synthetic-tests/payment','fixture',1)");
        a=(String)sessions.create("alice-id","alice").get("token");
        b=(String)sessions.create("bob-id","bob").get("token");
    }
    MvcResult call(MockHttpServletRequestBuilder req, String token, Object body) throws Exception {
        if (token!=null) req.header("Authorization","Bearer "+token);
        if (body!=null) req.contentType(MediaType.APPLICATION_JSON).content(json.writeValueAsBytes(body));
        return mvc.perform(req).andReturn();
    }
    JsonNode parsed(MvcResult result) throws Exception { return json.readTree(result.getResponse().getContentAsString()); }
    JsonNode expect(MvcResult result,int status) throws Exception {
        assertThat(result.getResponse().getStatus()).withFailMessage(result.getResponse().getContentAsString()).isEqualTo(status);
        return parsed(result);
    }
    String draft(String user,int qty) {
        String id=UUID.randomUUID().toString();
        db.update("INSERT INTO order_drafts(id,user_id,grant_hash,request_key,request_hash,status,version,total_price,created_at,expires_at,recipient_name,recipient_phone,recipient_address) VALUES (?,?,?,?,?,'CONFIRMED',2,?,?,?,'合成用户','13800138000','合成测试地址')",
                id,user+"-id",SessionService.digest(id),UUID.randomUUID().toString(),SessionService.digest(id),new BigDecimal("10.80").multiply(BigDecimal.valueOf(qty)),sessions.now(),sessions.now()+900);
        db.update("INSERT INTO order_draft_items VALUES (?,1,'虚构支付测试',?,10.80,1)",id,qty);
        return id;
    }
    String checkout(String user,String token,int qty) throws Exception {
        return expect(call(post("/api/order-drafts/"+draft(user,qty)+"/checkout").header("Idempotency-Key",UUID.randomUUID().toString()),token,Map.of("expectedVersion",2)),200).get("orderId").asText();
    }
    JsonNode grant(String id,String token) throws Exception {
        return expect(call(post("/api/orders/"+id+"/payment-authorizations"),token,Map.of("expectedVersion",1,"password","123456")),200);
    }
    MvcResult pay(String id,String user,String grant,String key) throws Exception {
        return call(post("/api/orders/"+id+"/pay").header("Idempotency-Key",key).header("X-Payment-Authorization",grant),user,Map.of("expectedVersion",1));
    }
    long count(String table) { return db.queryForObject("SELECT COUNT(*) FROM "+table,Long.class); }
    void registered(String id, String key, long age) {
        db.update("INSERT INTO payment_operation_requests(user_id,operation,request_key,request_hash,target_id,status,created_at) VALUES ('alice-id','PAY',?,?,?,'REGISTERED',?)",key,SessionService.digest("PAY|"+id+"|1"),id,sessions.now()-age);
    }

    @Test void abandonedRequestIsFencedAndLatePaymentCannotDebit() throws Exception {
        String id=checkout("alice",a,1); var cap=grant(id,a); registered(id,"abandoned-key",121);
        assertThat(recovery.reconcile()).isEqualTo(1);
        assertThat(expect(pay(id,a,cap.get("token").asText(),"abandoned-key"),409).get("code").asText()).isEqualTo("PAYMENT_ATTEMPT_EXPIRED");
        balance("100.00"); assertThat(count("payment_records")).isZero(); assertThat(count("transactions")).isZero();
        assertThat(db.queryForObject("SELECT stock FROM medicines WHERE id=1",Integer.class)).isEqualTo(10);
        assertThat(db.queryForObject("SELECT status FROM payment_authorizations",String.class)).isEqualTo("REVOKED");
    }

    @Test void freshRequestsAreNotReconciledAndPaidAuditRepairsOnlyRequestMetadata() throws Exception {
        String id=checkout("alice",a,1); var cap=grant(id,a); registered(id,"fresh-request",0);
        assertThat(recovery.reconcile()).isZero(); expect(pay(id,a,cap.get("token").asText(),"fresh-request"),200);
        db.update("UPDATE payment_operation_requests SET status='REGISTERED',order_id=NULL,created_at=? WHERE operation='PAY'",sessions.now()-121);
        assertThat(recovery.reconcile()).isEqualTo(1);
        assertThat(db.queryForObject("SELECT status FROM payment_operation_requests WHERE operation='PAY'",String.class)).isEqualTo("SUCCEEDED");
        balance("89.20"); assertThat(count("payment_records")).isEqualTo(1); assertThat(count("transactions")).isEqualTo(1);
    }

    @Test void staleExpiredOrderClosesWithoutFinancialEffects() throws Exception {
        String id=checkout("alice",a,1); grant(id,a); registered(id,"expired-request",121);
        db.update("UPDATE orders SET payment_expires_at=? WHERE id=?",sessions.now()-1,id);
        assertThat(recovery.reconcile()).isEqualTo(1);
        assertThat(db.queryForObject("SELECT payment_status FROM orders WHERE id=?",String.class,id)).isEqualTo("CLOSED");
        assertThat(db.queryForObject("SELECT rejection_code FROM payment_operation_requests WHERE operation='PAY'",String.class)).isEqualTo("ORDER_EXPIRED");
        balance("100.00"); assertThat(count("transactions")).isZero();
    }

    @Test void reconciliationWaitsForRunningFinancialTransaction() throws Exception {
        String id=checkout("alice",a,1); var cap=grant(id,a); registered(id,"running-request",121);
        CountDownLatch debited=new CountDownLatch(1), release=new CountDownLatch(1);
        doAnswer(invocation -> { debited.countDown(); if (!release.await(5,TimeUnit.SECONDS)) throw new IllegalStateException("Test barrier timeout"); return null; }).when(hooks).afterDebit(id);
        ExecutorService pool=Executors.newFixedThreadPool(2);
        try {
            Future<MvcResult> paying=pool.submit(() -> pay(id,a,cap.get("token").asText(),"running-request"));
            assertThat(debited.await(5,TimeUnit.SECONDS)).isTrue();
            Future<Integer> reconciling=pool.submit(() -> recovery.reconcile());
            org.assertj.core.api.Assertions.assertThatThrownBy(() -> reconciling.get(150,TimeUnit.MILLISECONDS)).isInstanceOf(TimeoutException.class);
            release.countDown(); expect(paying.get(5,TimeUnit.SECONDS),200);
            assertThat(reconciling.get(5,TimeUnit.SECONDS)).isZero(); balance("89.20"); assertThat(count("payment_records")).isEqualTo(1);
        } finally { release.countDown(); pool.shutdownNow(); }
    }
    void balance(String value) { assertThat(db.queryForObject("SELECT balance FROM users WHERE id='alice-id'",BigDecimal.class)).isEqualByComparingTo(value); }

    @Test void checkoutIsUnpaidUniqueImmutableAndBoundToFingerprint() throws Exception {
        String d=draft("alice",2);
        String path="/api/order-drafts/"+d+"/checkout";
        var first=expect(call(post(path).header("Idempotency-Key","checkout-0001"),a,Map.of("expectedVersion",2)),200);
        db.update("UPDATE order_drafts SET expires_at=0 WHERE id=?",d);
        var again=expect(call(post(path).header("Idempotency-Key","checkout-0002"),a,Map.of("expectedVersion",2)),200);
        assertThat(again.get("orderId")).isEqualTo(first.get("orderId"));
        assertThat(expect(call(post(path).header("Idempotency-Key","checkout-0001"),a,Map.of("expectedVersion",3)),409).get("code").asText()).isEqualTo("IDEMPOTENCY_CONFLICT");
        balance("100"); assertThat(count("orders")).isEqualTo(1); assertThat(count("transactions")).isZero();
        assertThat(first.get("paymentStatus").asText()).isEqualTo("PENDING_PAYMENT");
        assertThat(first.get("items").get(0).get("name").asText()).isEqualTo("虚构支付测试");
    }
    @Test void paymentAtomicallyCommitsAndReplaysEvenWithConsumedAuthorization() throws Exception {
        String id=checkout("alice",a,2); var g=grant(id,a);
        balance("100"); assertThat(g.get("amount").asText()).isEqualTo("21.60");
        assertThat(db.queryForObject("SELECT token_hash FROM payment_authorizations",String.class)).isNotEqualTo(g.get("token").asText());
        var receipt=expect(pay(id,a,g.get("token").asText(),"payment-0001"),200);
        assertThat(expect(pay(id,a,g.get("token").asText(),"payment-0001"),200)).isEqualTo(receipt);
        assertThat(expect(pay(id,a,g.get("token").asText(),"payment-0002"),200)).isEqualTo(receipt);
        balance("78.40"); assertThat(count("transactions")).isEqualTo(1); assertThat(count("payment_records")).isEqualTo(1);
        assertThat(db.queryForObject("SELECT stock FROM medicines WHERE id=1",Integer.class)).isEqualTo(8);
        assertThat(db.queryForObject("SELECT points FROM users WHERE id='alice-id'",Integer.class)).isEqualTo(21);
        assertThat(expect(call(get("/api/orders/"+id).param("paymentRequestKey","payment-0001"),a,null),200).get("requestOutcome").get("status").asText()).isEqualTo("SUCCEEDED");
        expect(call(post("/api/orders/"+id+"/close"),a,Map.of("expectedVersion",2)),409);
    }
    @Test void definiteRejectionCommitsRevocationAndDoesNotMoveMoney() throws Exception {
        String id=checkout("alice",a,1); var g=grant(id,a);
        db.update("UPDATE users SET balance=0 WHERE id='alice-id'");
        assertThat(expect(pay(id,a,g.get("token").asText(),"insufficient-1"),422).get("code").asText()).isEqualTo("INSUFFICIENT_BALANCE");
        assertThat(db.queryForObject("SELECT status FROM payment_authorizations",String.class)).isEqualTo("REVOKED");
        assertThat(count("transactions")).isZero();
        db.update("UPDATE users SET balance=100 WHERE id='alice-id'");
        expect(pay(id,a,g.get("token").asText(),"insufficient-1"),422);
        expect(pay(id,a,g.get("token").asText(),"insufficient-2"),401);
        var newGrant=grant(id,a); expect(pay(id,a,newGrant.get("token").asText(),"insufficient-3"),200);
    }
    @Test void priceChangeClosesAndOldSnapshotCannotPay() throws Exception {
        String id=checkout("alice",a,1); var g=grant(id,a);
        db.update("UPDATE medicines SET price=11 WHERE id=1");
        expect(pay(id,a,g.get("token").asText(),"price-change-1"),409);
        assertThat(db.queryForObject("SELECT close_reason FROM orders WHERE id=?",String.class,id)).isEqualTo("CATALOG_CHANGED");
        assertThat(db.queryForObject("SELECT status FROM payment_authorizations",String.class)).isEqualTo("REVOKED");
        balance("100"); assertThat(count("payment_records")).isZero();
    }
    @Test void expiredOrRevokedGrantCannotPayAndNewerGrantSurvivesLateCleanup() throws Exception {
        String id=checkout("alice",a,1); var old=grant(id,a); var current=grant(id,a);
        expect(call(delete("/api/orders/"+id+"/payment-authorizations").param("authorizationId",old.get("authorizationId").asText()),a,null),200);
        expect(pay(id,a,old.get("token").asText(),"old-grant-01"),401);
        expect(pay(id,a,current.get("token").asText(),"new-grant-01"),200);
    }
    @Test void expiresOrderAndRetainsLegacyUnverified() throws Exception {
        String id=checkout("alice",a,1);
        db.update("UPDATE orders SET payment_expires_at=0 WHERE id=?",id);
        var view=expect(call(get("/api/orders/"+id),a,null),200);
        assertThat(view.get("paymentStatus").asText()).isEqualTo("CLOSED");
        assertThat(view.get("closeReason").asText()).isEqualTo("EXPIRED");
        db.update("INSERT INTO orders(id,user_id,total_price,status) VALUES ('legacy','alice-id',10,'completed')");
        assertThat(expect(call(get("/api/orders/legacy"),a,null),200).get("paymentStatus").asText()).isEqualTo("LEGACY_UNVERIFIED");
        expect(call(post("/api/orders/legacy/payment-authorizations"),a,Map.of("expectedVersion",1,"password","123456")),409);
    }
    @Test void authorizationRolesOwnershipStrictJsonAndLegacyBypass() throws Exception {
        String id=checkout("alice",a,1);
        String read=(String)sessions.delegate(sessions.resolve(a)).get("token");
        String prepare=(String)sessions.delegateOrder(sessions.resolve(a)).get("token");
        for (String token : List.of(read,prepare)) {
            expect(call(post("/api/orders/"+id+"/payment-authorizations"),token,Map.of("expectedVersion",1,"password","123456")),403);
            expect(pay(id,token,"x".repeat(43),"forbidden-001"),403);
        }
        expect(call(get("/api/orders/"+id),b,null),404);
        expect(call(post("/api/orders/"+id+"/payment-authorizations"),a,Map.of("expectedVersion",1,"password",123456)),400);
        expect(call(post("/api/orders/"+id+"/payment-authorizations"),a,Map.of("expectedVersion",1,"password","字".repeat(30))),400);
        expect(call(post("/api/orders/"+id+"/payment-authorizations"),a,Map.of("expectedVersion",1,"password","123456","amount","0.01")),400);
        expect(call(post("/api/orders/"+id+"/close"),a,Map.of("expectedVersion",1.5)),400);
        expect(call(post("/api/orders").header("Idempotency-Key","legacy-bypass"),a,Map.of("userId","alice","recipientName","合成","recipientPhone","13800138000","recipientAddress","合成地址","walletPassword","123456","items",List.of(Map.of("medicineId",1,"quantity",1)))),409);
        assertThat(count("transactions")).isZero();
    }
    @Test void passwordLockPersistsAndDoesNotIssueGrant() throws Exception {
        String id=checkout("alice",a,1);
        for (int n=0;n<5;n++) expect(call(post("/api/orders/"+id+"/payment-authorizations"),a,Map.of("expectedVersion",1,"password","wrong")),401);
        expect(call(post("/api/orders/"+id+"/payment-authorizations"),a,Map.of("expectedVersion",1,"password","123456")),429);
        assertThat(count("payment_authorizations")).isZero();
        assertThat(db.queryForObject("SELECT locked_until FROM security_attempts WHERE attempt_key='pay:alice'",Long.class)).isGreaterThan(sessions.now());
        balance("100");
    }
    @Test void failureAfterDebitRollsBackAllEffectsAndSameRequestCanRecover() throws Exception {
        String id=checkout("alice",a,1); var g=grant(id,a);
        doThrow(new IllegalStateException("synthetic failure")).when(hooks).afterDebit(id);
        assertThat(expect(pay(id,a,g.get("token").asText(),"rollback-0001"),503).get("outcome").asText()).isEqualTo("NOT_APPLIED");
        balance("100"); assertThat(count("transactions")).isZero(); assertThat(count("payment_records")).isZero();
        assertThat(db.queryForObject("SELECT stock FROM medicines WHERE id=1",Integer.class)).isEqualTo(10);
        assertThat(db.queryForObject("SELECT status FROM payment_authorizations",String.class)).isEqualTo("ACTIVE");
        org.mockito.Mockito.reset(hooks);
        expect(pay(id,a,g.get("token").asText(),"rollback-0001"),200);
    }
    @Test void concurrentDifferentKeysStillDebitOnce() throws Exception {
        String id=checkout("alice",a,1); var g=grant(id,a);
        try (var pool=Executors.newFixedThreadPool(2)) {
            var results=pool.invokeAll(List.<Callable<Integer>>of(
                ()->pay(id,a,g.get("token").asText(),"concurrent-01").getResponse().getStatus(),
                ()->pay(id,a,g.get("token").asText(),"concurrent-02").getResponse().getStatus()));
            for (var result:results) assertThat(result.get()).isEqualTo(200);
        }
        balance("89.20"); assertThat(count("payment_records")).isEqualTo(1);
    }
    @Test void competingUsersCannotOversellAndCloseRaceHasOneWinner() throws Exception {
        String one=checkout("alice",a,1); String two=checkout("bob",b,1);
        var ga=grant(one,a); var gb=grant(two,b); db.update("UPDATE medicines SET stock=1 WHERE id=1");
        try (var pool=Executors.newFixedThreadPool(2)) {
            var results=pool.invokeAll(List.<Callable<Integer>>of(
                ()->pay(one,a,ga.get("token").asText(),"last-stock-a").getResponse().getStatus(),
                ()->pay(two,b,gb.get("token").asText(),"last-stock-b").getResponse().getStatus()));
            assertThat(List.of(results.get(0).get(),results.get(1).get())).containsExactlyInAnyOrder(200,409);
        }
        assertThat(count("payment_records")).isEqualTo(1);
        assertThat(db.queryForObject("SELECT SUM(balance) FROM users",BigDecimal.class)).isEqualByComparingTo("189.20");
        db.update("UPDATE medicines SET stock=10 WHERE id=1");
        String third=checkout("alice",a,1); var gc=grant(third,a);
        try (var pool=Executors.newFixedThreadPool(2)) {
            var results=pool.invokeAll(List.<Callable<Integer>>of(
                ()->pay(third,a,gc.get("token").asText(),"close-race-01").getResponse().getStatus(),
                ()->call(post("/api/orders/"+third+"/close"),a,Map.of("expectedVersion",1)).getResponse().getStatus()));
            assertThat(List.of(results.get(0).get(),results.get(1).get())).containsExactlyInAnyOrder(200,409);
        }
    }
    @Test void logoutInvalidatesCapabilityButPreservesPaidAudit() throws Exception {
        String id=checkout("alice",a,1); var g=grant(id,a);
        sessions.logout(sessions.resolve(a));
        String fresh=(String)sessions.create("alice-id","alice").get("token");
        expect(pay(id,fresh,g.get("token").asText(),"expired-parent"),401);
        var current=grant(id,fresh); expect(pay(id,fresh,current.get("token").asText(),"fresh-parent1"),200);
        sessions.logout(sessions.resolve(fresh));
        assertThat(count("payment_records")).isEqualTo(1); assertThat(count("transactions")).isEqualTo(1);
        assertThat(count("payment_authorizations")).isZero();
    }
    @Test void expiredAuthorizationAndStockRejectDoNotCloseOrder() throws Exception {
        String id=checkout("alice",a,1); var g=grant(id,a);
        db.update("UPDATE payment_authorizations SET created_at=?,expires_at=?",sessions.now()-61,sessions.now()-1);
        expect(pay(id,a,g.get("token").asText(),"expired-grant1"),401);
        var fresh=grant(id,a); db.update("UPDATE medicines SET stock=0 WHERE id=1");
        assertThat(expect(pay(id,a,fresh.get("token").asText(),"out-of-stock1"),409).get("code").asText()).isEqualTo("OUT_OF_STOCK");
        assertThat(db.queryForObject("SELECT payment_status FROM orders WHERE id=?",String.class,id)).isEqualTo("PENDING_PAYMENT");
        assertThat(db.queryForObject("SELECT COUNT(*) FROM payment_authorizations WHERE status='ACTIVE'",Integer.class)).isZero();
        balance("100");
    }
    @Test void qualificationChangeClosesAndPointsOverflowRejectsAtomically() throws Exception {
        String id=checkout("alice",a,1); var g=grant(id,a);
        db.update("UPDATE medicines SET qualification_version=2 WHERE id=1");
        assertThat(expect(pay(id,a,g.get("token").asText(),"qualification1"),409).get("code").asText()).isEqualTo("QUALIFICATION_CHANGED");
        balance("100"); assertThat(count("transactions")).isZero();
        db.update("UPDATE medicines SET qualification_version=1 WHERE id=1");
        id=checkout("alice",a,1); g=grant(id,a);
        db.update("UPDATE users SET points=? WHERE id='alice-id'",Integer.MAX_VALUE);
        expect(pay(id,a,g.get("token").asText(),"points-limit1"),422);
        balance("100"); assertThat(count("transactions")).isZero();
    }
    @Test void amountOverflowAndUnconfirmedOrExpiredDraftCannotConvert() throws Exception {
        String id=draft("alice",1);
        db.update("UPDATE order_drafts SET status='PREPARED' WHERE id=?",id);
        expect(call(post("/api/order-drafts/"+id+"/checkout").header("Idempotency-Key","unconfirmed1"),a,Map.of("expectedVersion",2)),409);
        db.update("UPDATE order_drafts SET status='CONFIRMED',expires_at=0 WHERE id=?",id);
        expect(call(post("/api/order-drafts/"+id+"/checkout").header("Idempotency-Key","expired-draft1"),a,Map.of("expectedVersion",2)),409);
        assertThat(count("orders")).isZero(); balance("100");
        id=draft("alice",99);
        db.update("UPDATE medicines SET price=99999999.99,stock=100 WHERE id=1");
        db.update("UPDATE order_draft_items SET price=99999999.99 WHERE draft_id=?",id);
        assertThat(expect(call(post("/api/order-drafts/"+id+"/checkout").header("Idempotency-Key","amount-overflow1"),a,Map.of("expectedVersion",2)),400)
                .get("code").asText()).isEqualTo("AMOUNT_OUT_OF_RANGE");
    }
    @Test void successfulReplayIgnoresSpentTokenButChangedBodyConflicts() throws Exception {
        String id=checkout("alice",a,1); var g=grant(id,a); String token=g.get("token").asText();
        expect(pay(id,a,token,"fingerprint01"),200);
        expect(call(post("/api/orders/"+id+"/pay").header("Idempotency-Key","fingerprint01")
                .header("X-Payment-Authorization",token),a,Map.of("expectedVersion",2)),409);
        expect(call(post("/api/orders/"+id+"/pay").header("Idempotency-Key","fingerprint02"),a,Map.of("expectedVersion",1)),400);
        balance("89.20"); assertThat(count("payment_records")).isEqualTo(1);
    }
    @Test void agentSummaryHasAuthoritativeStateButNoPrivatePaymentFields() throws Exception {
        String id=checkout("alice",a,1); var g=grant(id,a); expect(pay(id,a,g.get("token").asText(),"summary-paid1"),200);
        String read=(String)sessions.delegate(sessions.resolve(a)).get("token");
        var summary=expect(call(get("/internal/ai/v1/orders/"+id).header("X-AI-Service-Key","test-service-key-at-least-32-characters"),read,null),200);
        assertThat(summary.get("status").asText()).isEqualTo("PAID");
        String text=summary.toString();
        for (String denied : List.of("recipient","authorization","ledgerId","13800138000")) assertThat(text).doesNotContain(denied);
        assertThat(expect(call(get("/api/orders"),a,null),200).size()).isEqualTo(1);
        expect(call(post("/api/orders/"+id+"/close"),a,Map.of("expectedVersion",true)),400);
    }
}
