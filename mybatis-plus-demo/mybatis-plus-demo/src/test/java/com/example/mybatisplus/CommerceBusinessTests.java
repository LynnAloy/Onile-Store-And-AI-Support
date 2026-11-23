package com.example.mybatisplus;

import com.example.mybatisplus.service.AutoOrderService;
import com.example.mybatisplus.service.PurchaseGrounding;
import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MvcResult;
import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@TestPropertySource(properties={"commerce.enabled=true","commerce.evidence-enabled=true","payments.enabled=true",
    "payments.recovery-scheduling-enabled=false",
    "spring.datasource.url=jdbc:h2:mem:m6;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1",
    "spring.sql.init.schema-locations=classpath:sql/test-schema.sql,classpath:sql/m1-security-tables.sql,classpath:sql/m3-profile-schema.sql,classpath:sql/m4-draft-schema.sql,classpath:sql/m51-test-schema.sql,classpath:sql/m6-test-schema.sql"})
@org.springframework.boot.test.context.SpringBootTest
@org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
@org.springframework.test.context.ActiveProfiles("test")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class CommerceBusinessTests {
    @org.springframework.beans.factory.annotation.Autowired org.springframework.test.web.servlet.MockMvc mvc;
    @org.springframework.beans.factory.annotation.Autowired org.springframework.jdbc.core.JdbcTemplate db;
    @org.springframework.beans.factory.annotation.Autowired com.fasterxml.jackson.databind.ObjectMapper json;
    @org.springframework.beans.factory.annotation.Autowired com.example.mybatisplus.security.SessionService sessions;
    @org.springframework.beans.factory.annotation.Autowired org.springframework.security.crypto.password.PasswordEncoder encoder;
    @org.springframework.boot.test.mock.mockito.SpyBean com.example.mybatisplus.service.PaymentHooks hooks;
    String pin, a, b;
    @BeforeAll void hashes() { pin=encoder.encode("123456"); }
    MvcResult call(org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder req,String token,Object body) throws Exception {
        if (token!=null) req.header("Authorization","Bearer "+token);
        if (body!=null) req.contentType(org.springframework.http.MediaType.APPLICATION_JSON).content(json.writeValueAsBytes(body));
        return mvc.perform(req).andReturn();
    }
    JsonNode expect(MvcResult result,int status) throws Exception {
        assertThat(result.getResponse().getStatus()).withFailMessage(result.getResponse().getContentAsString()).isEqualTo(status);
        return json.readTree(result.getResponse().getContentAsString());
    }
    long count(String table) { return db.queryForObject("SELECT COUNT(*) FROM "+table,Long.class); }
    void balance(String value) { assertThat(db.queryForObject("SELECT balance FROM users WHERE id='alice-id'",BigDecimal.class)).isEqualByComparingTo(value); }
    @BeforeEach void reset() {
        for (String table:List.of("medicine_evidence","auto_order_turns","auto_order_policy_audit","auto_order_policies","medicine_admin_audit","account_roles")) db.update("DELETE FROM "+table);
        org.mockito.Mockito.reset(hooks);
        for (String table:List.of("payment_records","payment_operation_requests","payment_authorizations","order_items","transactions","checkout_requests","orders","order_draft_items","order_drafts","order_agent_grants","profile_consent_events","auth_sessions","security_attempts","recharge_cards","medicines","users")) db.update("DELETE FROM "+table);
        for (String name:List.of("alice","bob")) db.update("INSERT INTO users(id,user_id,password,balance,points,wallet_activated,walletPassword) VALUES (?,?,?,100,0,TRUE,?)",name+"-id",name,pin,pin);
        db.update("INSERT INTO medicines(id,name,price,stock,sale_classification,review_status,reference_source,reviewed_by,qualification_version) VALUES (1,'虚构支付测试',10.00,100,'OTC','APPROVED','local://synthetic-tests/payment','fixture',1)");
        a=(String)sessions.create("alice-id","alice").get("token");
        b=(String)sessions.create("bob-id","bob").get("token");
        db.update("UPDATE users SET health_notes='无其他健康风险',age=30,ai_profile_consent=TRUE,medical_history_text='无',allergies_text='无',medications_text='无',name='合成收货人',phone_num='13800138000',address='合成地址',balance=1000 WHERE id='alice-id'");
        db.update("UPDATE medicines SET stock=100,price=10.00 WHERE id=1");
        db.update("INSERT INTO medicine_evidence VALUES (1,1,1,?,'fixture',?)", "{\"categories\":[\"synthetic\"],\"ingredients\":[\"synthetic\"],\"indications\":\"synthetic only\",\"source\":\"local://synthetic-tests/p1\",\"maxUnitsPerOrder\":99}",sessions.now());
    }
    void setupAuto() throws Exception { enable(0,true,50,200,"123456"); }
    JsonNode enable(long version,boolean enabled,int single,int daily,String password) throws Exception {
        var body=new LinkedHashMap<String,Object>();
        body.put("enabled",enabled); body.put("perOrderLimit",single); body.put("dailyLimit",daily); body.put("expectedVersion",version);
        if (password!=null) body.put("password",password);
        return expect(call(put("/api/wallet/auto-order-policy"),a,body),200);
    }
    String autoTurn(String message) throws Exception {
        String id=UUID.randomUUID().toString();
        expect(call(post("/api/auto-orders/turns"),a,Map.of("turnId",id,"conversationId","synthetic-conversation","message",message)),200);
        return id;
    }
    MvcResult execute(String id,int quantity) throws Exception {
        return call(post("/api/auto-orders/turns/"+id+"/execute"),a,Map.of("items",List.of(Map.of("medicineId",1,"quantity",quantity))));
    }
    @Test void defaultOffAndNoPinCannotEnableOrIncreaseLimits() throws Exception {
        var policy=expect(call(get("/api/wallet/auto-order-policy"),a,null),200);
        assertThat(policy.get("enabled").asBoolean()).isFalse();
        assertThat(policy.get("perOrderLimit").decimalValue()).isEqualByComparingTo("50");
        expect(call(put("/api/wallet/auto-order-policy"),a,Map.of("enabled",true,"perOrderLimit",50,"dailyLimit",200,"expectedVersion",0)),409);
        setupAuto();
        expect(call(put("/api/wallet/auto-order-policy"),a,Map.of("enabled",true,"perOrderLimit",60,"dailyLimit",200,"expectedVersion",1)),409);
        assertThat(db.queryForObject("SELECT COUNT(*) FROM auto_order_policy_audit",Integer.class)).isEqualTo(1);
    }
    @Test void duplicateTurnSettlesOnceWithShippingAndNoPersonalDataInReceipt() throws Exception {
        setupAuto(); String id=autoTurn("帮我下单2件虚构支付测试");
        var receipt=expect(execute(id,2),200);
        assertThat(receipt.get("status").asText()).isEqualTo("PAID");
        assertThat(expect(execute(id,2),200).get("orderId")).isEqualTo(receipt.get("orderId"));
        assertThat(count("payment_records")).isEqualTo(1); assertThat(count("transactions")).isEqualTo(1);
        balance("980.00");
        assertThat(db.queryForObject("SELECT recipient_address FROM orders",String.class)).isEqualTo("合成地址");
        assertThat(receipt.toString()).doesNotContain("合成地址","13800138000","合成收货人","token","password");
        expect(execute(id,1),409);
    }
    @Test void disabledOrChangedProfileRejectsLateTurn() throws Exception {
        setupAuto(); String id=autoTurn("帮我下单1件虚构支付测试");
        enable(1,false,50,200,null);
        assertThat(expect(execute(id,1),409).get("code").asText()).isEqualTo("AUTO_AUTH_REVOKED");
        enable(2,true,50,200,"123456");
        String next=autoTurn("帮我下单1件虚构支付测试");
        db.update("UPDATE users SET profile_context_version=profile_context_version+1 WHERE id='alice-id'");
        assertThat(expect(execute(next,1),409).get("code").asText()).isEqualTo("PROFILE_CHANGED");
        assertThat(count("payment_records")).isZero(); balance("1000.00");
    }
    @Test void singleAndDailyLimitsPersistAcrossTogglesAndLogin() throws Exception {
        setupAuto();
        assertThat(expect(execute(autoTurn("帮我下单6件虚构支付测试"),6),409).get("code").asText()).isEqualTo("PER_ORDER_LIMIT");
        for (int i=0;i<4;i++) expect(execute(autoTurn("帮我下单5件虚构支付测试"),5),200);
        enable(1,false,50,200,null); enable(2,true,50,200,"123456");
        assertThat(expect(execute(autoTurn("帮我下单1件虚构支付测试"),1),409).get("code").asText()).isEqualTo("DAILY_LIMIT");
        a=(String)sessions.create("alice-id","alice").get("token");
        var policy=expect(call(get("/api/wallet/auto-order-policy"),a,null),200);
        assertThat(policy.get("enabled").asBoolean()).isFalse();
        assertThat(policy.get("dailySpent").decimalValue()).isEqualByComparingTo("200");
        assertThat(count("payment_records")).isEqualTo(4); balance("800.00");
    }
    @Test void concurrentDailyRequestsCannotOverspend() throws Exception {
        enable(0,true,50,50,"123456");
        String one=autoTurn("帮我下单4件虚构支付测试"), two=autoTurn("帮我下单4件虚构支付测试");
        var pool=Executors.newFixedThreadPool(2);
        try {
            var f1=pool.submit(() -> execute(one,4)); var f2=pool.submit(() -> execute(two,4));
            var codes=List.of(f1.get(10,TimeUnit.SECONDS).getResponse().getStatus(),f2.get(10,TimeUnit.SECONDS).getResponse().getStatus());
            assertThat(codes).containsExactlyInAnyOrder(200,409);
            assertThat(count("payment_records")).isEqualTo(1); balance("960.00");
        } finally { pool.shutdownNow(); }
    }
    @Test void sameTurnConcurrentReplayOnlyChargesOnce() throws Exception {
        setupAuto(); String id=autoTurn("帮我下单2件虚构支付测试");
        var pool=Executors.newFixedThreadPool(2);
        try {
            var f1=pool.submit(() -> execute(id,2)); var f2=pool.submit(() -> execute(id,2));
            assertThat(expect(f1.get(10,TimeUnit.SECONDS),200).get("orderId"))
                    .isEqualTo(expect(f2.get(10,TimeUnit.SECONDS),200).get("orderId"));
            assertThat(count("payment_records")).isEqualTo(1); balance("980.00");
        } finally { pool.shutdownNow(); }
    }
    @Test void settlementFailureRollsBackOrderDebitStockPointsAndBudget() throws Exception {
        setupAuto(); String id=autoTurn("帮我下单2件虚构支付测试");
        doThrow(new IllegalStateException("synthetic failure")).when(hooks).afterDebit(anyString());
        assertThat(expect(execute(id,2),503).get("outcome").asText()).isEqualTo("UNKNOWN");
        assertThat(count("payment_records")).isZero(); assertThat(count("transactions")).isZero(); assertThat(count("orders")).isZero();
        balance("1000.00"); assertThat(db.queryForObject("SELECT stock FROM medicines",Integer.class)).isEqualTo(100);
        assertThat(db.queryForObject("SELECT SUM(amount) FROM auto_order_turns",BigDecimal.class)).isNull();
    }
    @Test void prescriptionUnreviewedStockBalanceAndIncompleteShippingAreRefused() throws Exception {
        setupAuto();
        for (String update:List.of("sale_classification='RX'","review_status='PENDING'","stock=0")) {
            db.update("UPDATE medicines SET "+update+" WHERE id=1");
            expect(execute(autoTurn("帮我下单1件虚构支付测试"),1),409);
            db.update("UPDATE medicines SET sale_classification='OTC',review_status='APPROVED',stock=100 WHERE id=1");
        }
        db.update("UPDATE users SET address=NULL WHERE id='alice-id'");
        assertThat(expect(execute(autoTurn("帮我下单1件虚构支付测试"),1),409).get("code").asText()).isEqualTo("SHIPPING_REQUIRED");
        db.update("UPDATE users SET address='合成地址',balance=0 WHERE id='alice-id'");
        assertThat(expect(execute(autoTurn("帮我下单1件虚构支付测试"),1),409).get("code").asText()).isEqualTo("INSUFFICIENT_BALANCE");
        assertThat(count("payment_records")).isZero();
    }
    @Test void arbitraryAgentOrOtherUserCannotSpendManageOrReadTurn() throws Exception {
        setupAuto(); String id=autoTurn("帮我下单1件虚构支付测试");
        expect(call(get("/api/auto-orders/turns/"+id),b,null),404);
        String agent=(String)sessions.delegate(sessions.resolve(a)).get("token");
        for (String path:List.of("/api/admin/medicines","/api/wallet/auto-order-policy","/api/auto-orders/turns/"+id))
            expect(call(get(path),agent,null),403);
        expect(call(post("/api/auto-orders/turns/"+id+"/execute"),agent,Map.of("items",List.of(Map.of("medicineId",1,"quantity",1)))),403);
        expect(call(get("/api/admin/medicines"),a,null),403);
        assertThat(count("payment_records")).isZero();
    }
    @Test void adminQualificationStockAuditVersionAndRoleRevocation() throws Exception {
        db.update("INSERT INTO account_roles VALUES ('alice-id','ADMIN',?)",sessions.now());
        expect(call(put("/api/admin/medicines/1/stock"),a,Map.of("expectedVersion",1,"expectedStock",100,"reason","合成补货")),400);
        expect(call(put("/api/admin/medicines/1/qualification"),a,Map.of("classification","OTC","reviewStatus","PENDING")),400);
        expect(call(put("/api/wallet/auto-order-policy"),a,Map.of("enabled",false,"perOrderLimit",50,"dailyLimit",200)),400);
        expect(call(put("/api/admin/medicines/1/qualification"),a,Map.of("expectedVersion",1,"classification","OTC","reviewStatus","APPROVED","referenceSource","")),400);
        expect(call(put("/api/admin/medicines/1/qualification"),a,Map.of("expectedVersion",1,"classification","RX","reviewStatus","APPROVED","referenceSource","local://synthetic-tests/m6")),200);
        expect(call(put("/api/admin/medicines/1/stock"),a,Map.of("expectedVersion",1,"expectedStock",100,"stock",50,"reason","合成补货")),409);
        expect(call(put("/api/admin/medicines/1/stock"),a,Map.of("expectedVersion",2,"expectedStock",99,"stock",50,"reason","合成补货")),409);
        expect(call(put("/api/admin/medicines/1/stock"),a,Map.of("expectedVersion",2,"expectedStock",100,"stock",50,"reason","合成补货")),200);
        assertThat(count("medicine_admin_audit")).isEqualTo(2);
        db.update("DELETE FROM account_roles WHERE user_id='alice-id'");
        expect(call(get("/api/admin/medicines"),a,null),403);
    }
    @Test void completeLiteralPurchaseRequiredAndQuantityCannotBeSwappedOrPartial() throws Exception {
        setupAuto();
        for (String text:List.of("不要下单1件虚构支付测试","如果买1件虚构支付测试多少钱")) {
            var result=expect(call(post("/api/auto-orders/turns"),a,Map.of("turnId",UUID.randomUUID().toString(),"conversationId","test","message",text)),200);
            assertThat(result.get("status").asText()).isEqualTo("MANUAL");
        }
        for (String text:List.of("帮我下单2件虚构支付测试", "帮我下单1件虚构支付测试，3件其他商品")) {
            assertThat(expect(execute(autoTurn(text),1),409).get("code").asText()).isEqualTo("EXPLICIT_PURCHASE_REQUIRED");
        }
        assertThat(count("payment_records")).isZero();
    }
    @Test void expiredTurnAndDuplicateCatalogNamesCannotSpend() throws Exception {
        setupAuto(); String id=autoTurn("帮我下单1件虚构支付测试");
        db.update("UPDATE auto_order_turns SET expires_at=? WHERE turn_id=?",sessions.now()-1,id);
        assertThat(expect(execute(id,1),409).get("code").asText()).isEqualTo("AUTO_TURN_EXPIRED");
        db.update("INSERT INTO medicines(id,name,price,stock) VALUES (2,'虚构支付测试',10,10)");
        assertThat(expect(execute(autoTurn("帮我下单1件虚构支付测试"),1),409).get("code").asText()).isEqualTo("SPECIFICATION_REQUIRED");
        assertThat(count("payment_records")).isZero();
    }
    @Test void loweringNeedsNoPinButReenableAndPinLockoutRemainEnforced() throws Exception {
        setupAuto(); enable(1,true,20,100,null);
        expect(call(put("/api/wallet/auto-order-policy"),a,Map.of("enabled",true,"perOrderLimit",20,"dailyLimit",100,"expectedVersion",1)),409);
        enable(2,false,20,100,null);
        for (int attempt=0;attempt<5;attempt++) {
            expect(call(put("/api/wallet/auto-order-policy"),a,Map.of("enabled",true,"perOrderLimit",20,"dailyLimit",100,"expectedVersion",3,"password","000000")),401);
        }
        expect(call(put("/api/wallet/auto-order-policy"),a,Map.of("enabled",true,"perOrderLimit",20,"dailyLimit",100,"expectedVersion",3,"password","123456")),429);
        assertThat(expect(call(get("/api/wallet/auto-order-policy"),a,null),200).get("enabled").asBoolean()).isFalse();
    }
    @Test void rejectedReplayIsTerminalAndTurnCannotBeReboundToAnotherMessage() throws Exception {
        setupAuto(); String id=autoTurn("帮我下单6件虚构支付测试");
        expect(execute(id,6),409);
        enable(1,true,100,200,"123456");
        assertThat(expect(execute(id,6),200).get("status").asText()).isEqualTo("REJECTED");
        expect(call(post("/api/auto-orders/turns"),a,Map.of("turnId",id,"conversationId","synthetic-conversation","message","帮我下单1件虚构支付测试")),409);
        assertThat(count("payment_records")).isZero();
    }
    @Test void catalogRequiresAgentReadAndServiceKey() throws Exception {
        String agent=(String)sessions.delegate(sessions.resolve(a)).get("token");
        expect(call(get("/internal/ai/v1/catalog"),agent,null),401);

    }
    @Test void serverRiskGateRejectsBypassingFrontendWithUnsafeOrMissingHealth() throws Exception {
        setupAuto();
        for (String change:List.of("ai_profile_consent=FALSE","age=NULL","age=70","allergies_text='过敏'","medications_text='正在用药'","medical_history_text=NULL","health_notes=NULL")) {
            db.update("UPDATE users SET "+change+" WHERE id='alice-id'");
            assertThat(expect(execute(autoTurn("帮我下单1件虚构支付测试"),1),409).get("code").asText()).isEqualTo("HEALTH_REVIEW_REQUIRED");
            db.update("UPDATE users SET ai_profile_consent=TRUE,age=30,allergies_text='无',medications_text='无',medical_history_text='无',health_notes='无其他健康风险' WHERE id='alice-id'");
        }
        assertThat(count("payment_records")).isZero(); balance("1000.00");
    }
    @Test void missingOrStaleEvidenceCannotSettleAndAdminCanReviewEvidence() throws Exception {
        setupAuto();
        db.update("DELETE FROM medicine_evidence");
        assertThat(expect(execute(autoTurn("帮我下单1件虚构支付测试"),1),409).get("code").asText()).isEqualTo("HEALTH_REVIEW_REQUIRED");
        var body=Map.of("expectedVersion",0,"qualificationVersion",1,"categories",List.of("合成类别"),"ingredients",List.of("合成成分"),"indications","合成用途，不用于真实医疗","source","local://synthetic-tests/p1","maxUnitsPerOrder",1);
        expect(call(put("/api/admin/medicines/1/evidence"),a,body),403);
        db.update("INSERT INTO account_roles VALUES ('alice-id','ADMIN',?)",sessions.now());
        expect(call(put("/api/admin/medicines/1/evidence"),a,body),200);
        expect(execute(autoTurn("帮我下单1件虚构支付测试"),1),200);
        expect(execute(autoTurn("帮我下单2件虚构支付测试"),2),409);
        db.update("UPDATE medicines SET qualification_version=2 WHERE id=1");
        expect(execute(autoTurn("帮我下单1件虚构支付测试"),1),409);
        var stale=expect(call(get("/api/admin/medicines/1/evidence"),a,null),200);
        assertThat(stale.get("status").asText()).isEqualTo("STALE");
        assertThat(count("payment_records")).isEqualTo(1);
    }
    @Test void fixedPacificStandardTimeDoesNotFollowDaylightSaving() {
        assertThat(AutoOrderService.budgetDay(Instant.parse("2026-07-01T07:59:59Z").getEpochSecond()).toString()).isEqualTo("2026-06-30");
        assertThat(AutoOrderService.budgetDay(Instant.parse("2026-07-01T08:00:00Z").getEpochSecond()).toString()).isEqualTo("2026-07-01");
        assertThat(AutoOrderService.budgetDay(Instant.parse("2026-12-01T07:59:59Z").getEpochSecond()).toString()).isEqualTo("2026-11-30");
        assertThat(PurchaseGrounding.exact("帮我下单5件枇杷露，3件布洛芬",List.of(Map.of("name","枇杷露","quantity",5),Map.of("name","布洛芬","quantity",3)))).isTrue();
    }
}
