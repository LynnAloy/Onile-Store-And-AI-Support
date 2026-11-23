package com.example.mybatisplus;

import com.example.mybatisplus.security.SessionService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class M1SecurityBusinessTests {
    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper json;
    @Autowired PasswordEncoder encoder;
    @Autowired SessionService sessions;
    @Autowired com.example.mybatisplus.mapper.UserMapper userMapper;
    @Autowired org.springframework.transaction.PlatformTransactionManager transactionManager;
    String hash;
    String pinHash;
    String alice;
    String bob;

    @BeforeAll
    void hashes() {
        hash = encoder.encode("Password123");
        pinHash = encoder.encode("123456");
    }

    @BeforeEach
    void reset() {
        for (String table : List.of("order_draft_items", "order_drafts", "order_agent_grants", "profile_consent_events", "checkout_requests", "auth_sessions", "security_attempts",
                "order_items", "transactions", "orders", "recharge_cards", "medicines", "users")) {
            jdbc.update("DELETE FROM " + table);
        }
        for (String name : List.of("alice", "bob")) {
            jdbc.update("INSERT INTO users(id,user_id,password,balance,points,wallet_activated,walletPassword) "
                    + "VALUES (?,?,?,100,100,TRUE,?)", name + "-id", name, hash, pinHash);
        }
        jdbc.update("INSERT INTO medicines(id,name,price,stock) VALUES (1,'药品一',10.80,10),(2,'药品二',7.90,10)");
        jdbc.update("UPDATE medicines SET sale_classification='OTC',review_status='APPROVED',"
                + "reference_source='local://synthetic-tests',reviewed_by='test-fixture',qualification_version=1");
        jdbc.update("INSERT INTO recharge_cards(id,amount,is_used) VALUES ('CARD-1',50,FALSE)");
        alice = (String) sessions.create("alice-id", "alice").get("token");
        bob = (String) sessions.create("bob-id", "bob").get("token");
    }

    MvcResult call(MockHttpServletRequestBuilder request, String token, Object body) throws Exception {
        if (token != null) request.header("Authorization", "Bearer " + token);
        if (body != null) request.contentType(MediaType.APPLICATION_JSON).content(json.writeValueAsBytes(body));
        return mvc.perform(request).andReturn();
    }

    JsonNode body(MvcResult result) throws Exception {
        return json.readTree(result.getResponse().getContentAsString());
    }

    void status(MvcResult result, int expected) throws Exception {
        assertThat(result.getResponse().getStatus())
                .withFailMessage(result.getResponse().getContentAsString()).isEqualTo(expected);
    }

    Map<String, Object> order() {
        Map<String, Object> order = new HashMap<>();
        order.put("userId", "alice");
        order.put("recipientName", "测试用户");
        order.put("recipientPhone", "13800138000");
        order.put("recipientAddress", "测试收货地址");
        order.put("walletPassword", "123456");
        order.put("items", List.of(Map.of("medicineId", 1, "quantity", 2)));
        return order;
    }

    MvcResult checkout(String token, Map<String, Object> payload, String key) throws Exception {
        return call(post("/api/orders").header("Idempotency-Key", key), token, payload);
    }

    int count(String table) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Integer.class);
    }

    BigDecimal balance(String username) {
        return jdbc.queryForObject("SELECT balance FROM users WHERE user_id=?", BigDecimal.class, username);
    }

    @Test
    void protectedRoutesRejectAnonymousAndForgedTokens() throws Exception {
        status(call(get("/api/user/profile"), null, null), 401);
        status(call(get("/api/user/profile"), "mock_token_alice", null), 401);
        status(call(post("/api/auth/activate-wallet"), null,
                Map.of("userId", "alice", "password", "123456")), 401);
        status(call(get("/message"), alice, null), 403);
    }

    Map<String, Object> healthDetails(boolean consent) {
        return Map.of("basic", Map.of("userId", "alice", "nickname", "健康测试", "age", 30,
                        "phoneNum", "13800138000", "medicalHistory", List.of("合成病史")),
                "health", Map.of("heightCm", 180, "weightKg", 72,
                        "medicalHistoryText", "仅用于测试的自述记录", "aiProfileConsent", consent));
    }

    Map<String, Object> intent(int quantity) {
        return Map.of("items", List.of(Map.of("medicineId", 1, "quantity", quantity)));
    }

    JsonNode orderGrant(String user) throws Exception {
        var result = call(post("/api/auth/order-agent-token"), user, intent(2));
        status(result, 200);
        return body(result);
    }

    MvcResult prepare(JsonNode grant, Object data) throws Exception {
        return call(post("/internal/ai/v1/order-drafts")
                .header("Idempotency-Key", grant.get("requestKey").asText())
                .header("X-AI-Service-Key", "test-service-key-at-least-32-characters"),
                grant.get("token").asText(), data);
    }

    Map<String, Object> confirmation(long version) {
        return Map.of("version", version, "recipientName", "合成收货人",
                "recipientPhone", "13800138000", "recipientAddress", "合成地址");
    }

    @Test
    void draftGrantHasIndependentScopeAndNoPaymentPermission() throws Exception {
        JsonNode grant = orderGrant(alice);
        String token = grant.get("token").asText();
        assertThat(grant.get("scope").asText()).isEqualTo("AGENT_ORDER_PREPARE");
        status(call(get("/api/user/profile"), token, null), 403);
        status(personal(token, "medicines"), 403);
        status(checkout(token, order(), "cannot-pay-draft"), 403);
        status(call(post("/internal/ai/v1/order-drafts").header("Idempotency-Key", "test-key"), token, intent(2)), 401);
        String read = body(call(post("/api/auth/agent-token"), alice, null)).get("token").asText();
        status(personal(read, "order-preparation"), 403);
        status(personal(token, "order-preparation"), 200);
    }

    @Test
    void draftGrantRejectsNumericCoercionAndDuplicateItems() throws Exception {
        for (Object quantity : List.of("2", 2.5, true)) {
            status(call(post("/api/auth/order-agent-token"), alice,
                    Map.of("items", List.of(Map.of("medicineId", 1, "quantity", quantity)))), 400);
        }
        status(call(post("/api/auth/order-agent-token"), alice,
                Map.of("items", List.of(Map.of("medicineId", 1, "quantity", 1),
                        Map.of("medicineId", 1, "quantity", 2)))), 400);
        assertThat(count("order_agent_grants")).isZero();
    }

    @Test
    void multiProductDraftCanonicalizesItemsAndUsesServerPrices() throws Exception {
        var data = Map.of("items", List.of(Map.of("medicineId", 2, "quantity", 3),
                Map.of("medicineId", 1, "quantity", 1)));
        JsonNode grant = body(call(post("/api/auth/order-agent-token"), alice, data));
        var result = prepare(grant, Map.of("items", List.of(Map.of("medicineId", 1, "quantity", 1),
                Map.of("medicineId", 2, "quantity", 3))));
        status(result, 200);
        assertThat(body(result).get("items").size()).isEqualTo(2);
        assertThat(body(result).get("totalPrice").asText()).isEqualTo("34.50");
        assertThat(count("orders")).isZero();
    }

    @Test
    void draftIntentAndIdempotencyAreServerBoundAndNeverDebit() throws Exception {
        JsonNode grant = orderGrant(alice);
        var first = prepare(grant, intent(2));
        status(first, 200);
        var repeated = prepare(grant, intent(2));
        status(repeated, 200);
        assertThat(body(first).get("draftId")).isEqualTo(body(repeated).get("draftId"));
        assertThat(body(first).get("totalPrice").asText()).isEqualTo("21.60");
        assertThat(body(first).get("paid").asBoolean()).isFalse();
        status(prepare(grant, intent(3)), 409);
        status(prepare(grant, Map.of("items", List.of(Map.of("medicineId", 1, "quantity", 2)), "userId", "bob")), 400);
        assertThat(count("order_drafts")).isEqualTo(1);
        assertThat(count("orders")).isZero();
        assertThat(balance("alice")).isEqualByComparingTo("100");
        assertThat(jdbc.queryForObject("SELECT stock FROM medicines WHERE id=1", Integer.class)).isEqualTo(10);
    }

    @Test
    void unknownUnreviewedAndPrescriptionProductsCannotPrepareOrBypassCheckout() throws Exception {
        JsonNode grant = orderGrant(alice);
        for (String classification : List.of("UNKNOWN", "RX")) {
            jdbc.update("UPDATE medicines SET sale_classification=? WHERE id=1", classification);
            status(prepare(grant, intent(2)), 409);
        }
        jdbc.update("UPDATE medicines SET sale_classification='OTC',review_status='PENDING' WHERE id=1");
        status(prepare(grant, intent(2)), 409);
        status(checkout(alice, order(), "unknown-must-not-sell"), 409);
        assertThat(count("order_drafts")).isZero();
        assertThat(count("orders")).isZero();
    }

    @Test
    void revokedGrantCannotWriteButSavedDraftRemainsRecoverableByUser() throws Exception {
        JsonNode grant = orderGrant(alice);
        JsonNode saved = body(prepare(grant, intent(2)));
        String id = saved.get("draftId").asText();
        status(call(delete("/api/auth/order-agent-token"), alice, null), 200);
        status(prepare(grant, intent(2)), 401);
        status(call(get("/api/order-drafts/" + id), alice, null), 200);
        status(call(get("/api/order-drafts/" + id), bob, null), 404);
        var recovered = call(get("/api/order-drafts").param("requestKey", grant.get("requestKey").asText()), alice, null);
        assertThat(body(recovered).size()).isEqualTo(1);
        assertThat(count("order_agent_grants")).isZero();
    }

    @Test
    void scopedLateGrantCleanupPreservesNewerAndOtherUsersGrants() throws Exception {
        JsonNode late = orderGrant(alice);
        String id = body(prepare(late, intent(2))).get("draftId").asText();
        JsonNode newer = orderGrant(alice);
        JsonNode other = orderGrant(bob);
        String key = late.get("requestKey").asText();
        status(call(delete("/api/auth/order-agent-token").param("requestKey", key), bob, null), 200);
        status(prepare(late, intent(2)), 200);
        status(call(delete("/api/auth/order-agent-token").param("requestKey", key), alice, null), 200);
        status(prepare(late, intent(2)), 401);
        status(prepare(newer, intent(2)), 200);
        status(prepare(other, intent(2)), 200);
        status(call(delete("/api/auth/order-agent-token").param("requestKey", "invalid"), alice, null), 400);
        status(prepare(newer, intent(2)), 200);
        status(call(get("/api/order-drafts/" + id), alice, null), 200);
    }

    @Test
    void draftConfirmIsVersionedIdempotentPrivateAndNotPayment() throws Exception {
        JsonNode grant = orderGrant(alice);
        String id = body(prepare(grant, intent(2))).get("draftId").asText();
        status(call(post("/api/order-drafts/" + id + "/confirm"), bob, confirmation(1)), 404);
        status(call(post("/api/order-drafts/" + id + "/confirm"), alice, confirmation(9)), 409);
        var result = call(post("/api/order-drafts/" + id + "/confirm"), alice, confirmation(1));
        status(result, 200);
        assertThat(body(result).get("status").asText()).isEqualTo("CONFIRMED");
        assertThat(body(result).get("version").asInt()).isEqualTo(2);
        status(call(post("/api/order-drafts/" + id + "/confirm"), alice, confirmation(1)), 200);
        assertThat(body(prepare(grant, intent(2))).has("recipientPhone")).isFalse();
        assertThat(count("orders")).isZero();
        assertThat(balance("alice")).isEqualByComparingTo("100");
    }

    @Test
    void draftConfirmRechecksPriceStockAndQualification() throws Exception {
        String id = body(prepare(orderGrant(alice), intent(2))).get("draftId").asText();
        jdbc.update("UPDATE medicines SET price=12 WHERE id=1");
        var changed = call(post("/api/order-drafts/" + id + "/confirm"), alice, confirmation(1));
        assertThat(body(changed).get("code").asText()).isEqualTo("PRICE_CHANGED");
        jdbc.update("UPDATE medicines SET price=10.80,stock=1 WHERE id=1");
        assertThat(body(call(post("/api/order-drafts/" + id + "/confirm"), alice, confirmation(1)))
                .get("code").asText()).isEqualTo("OUT_OF_STOCK");
        jdbc.update("UPDATE medicines SET stock=10,qualification_version=2 WHERE id=1");
        assertThat(body(call(post("/api/order-drafts/" + id + "/confirm"), alice, confirmation(1)))
                .get("code").asText()).isEqualTo("QUALIFICATION_CHANGED");
        assertThat(body(call(get("/api/order-drafts/" + id), alice, null)).get("canConfirm").asBoolean()).isFalse();
        assertThat(count("orders")).isZero();
    }

    @Test
    void expiredCancelledAndParentExpiredDraftFlowsRejectWrites() throws Exception {
        JsonNode grant = orderGrant(alice);
        String id = body(prepare(grant, intent(2))).get("draftId").asText();
        jdbc.update("UPDATE order_drafts SET expires_at=0 WHERE id=?", id);
        assertThat(body(call(get("/api/order-drafts/" + id), alice, null)).get("status").asText()).isEqualTo("EXPIRED");
        status(call(post("/api/order-drafts/" + id + "/confirm"), alice, confirmation(1)), 409);
        jdbc.update("UPDATE order_drafts SET expires_at=? WHERE id=?", sessions.now() + 900, id);
        status(call(post("/api/order-drafts/" + id + "/cancel"), alice, Map.of("version", 1)), 200);
        status(call(post("/api/order-drafts/" + id + "/cancel"), alice, Map.of("version", 1)), 200);
        status(call(post("/api/order-drafts/" + id + "/confirm"), alice, confirmation(1)), 409);
        jdbc.update("UPDATE auth_sessions SET expires_at=0 WHERE token_hash=?", SessionService.digest(alice));
        status(prepare(grant, intent(2)), 401);
    }

    @Test
    void concurrentDraftPreparationCreatesExactlyOneSnapshot() throws Exception {
        JsonNode grant = orderGrant(alice);
        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            var tasks = pool.invokeAll(List.of(() -> prepare(grant, intent(2)), () -> prepare(grant, intent(2))));
            for (var task : tasks) status((MvcResult) task.get(), 200);
            assertThat(count("order_drafts")).isEqualTo(1);
            assertThat(count("order_draft_items")).isEqualTo(1);
        } finally { pool.shutdownNow(); }
    }

    @Test
    void concurrentConfirmAndCancelHaveExactlyOneWinner() throws Exception {
        String id = body(prepare(orderGrant(alice), intent(2))).get("draftId").asText();
        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            var results = pool.invokeAll(List.of(
                    () -> call(post("/api/order-drafts/" + id + "/confirm"), alice, confirmation(1)),
                    () -> call(post("/api/order-drafts/" + id + "/cancel"), alice, Map.of("version", 1))));
            List<Integer> statuses = new ArrayList<>();
            for (var result : results) statuses.add(((MvcResult) result.get()).getResponse().getStatus());
            assertThat(statuses).containsExactlyInAnyOrder(200, 409);
            assertThat(count("orders")).isZero();
        } finally { pool.shutdownNow(); }
    }

    MvcResult personal(String token, String endpoint) throws Exception {
        return call(get("/internal/ai/v1/" + endpoint)
                .header("X-AI-Service-Key", "test-service-key-at-least-32-characters"), token, null);
    }

    @Test
    void delayedLogoutCannotRevokeNewLogin() {
        var original = sessions.resolve(alice);
        String replacement = (String) sessions.create(original.id(), original.username()).get("token");
        sessions.logout(original);
        assertThat(sessions.resolve(alice)).isNull();
        assertThat(sessions.resolve(replacement)).isNotNull();
    }

    @Test
    void preparedDraftPrefillsShippingOnlyForConsentingOwner() throws Exception {
        var basic = Map.of("userId", "alice", "name", "收货人", "phoneNum", "13800138000", "address", "收货地址");
        String profilePath = "/api/user/profile/details";
        status(call(put(profilePath), alice, Map.of("basic", basic, "health", Map.of("aiProfileConsent", false))), 200);
        JsonNode saved = body(prepare(orderGrant(alice), intent(2)));
        String path = "/api/order-drafts/" + saved.get("draftId").asText();
        assertThat(saved.has("recipientName")).isFalse();
        assertThat(body(call(get(path), alice, null)).get("recipientName").isNull()).isTrue();

        status(call(put(profilePath), alice, Map.of("basic", basic, "health", Map.of("aiProfileConsent", true))), 200);
        JsonNode prefilled = body(call(get(path), alice, null));
        assertThat(prefilled.get("shippingPrefilled").asBoolean()).isTrue();
        assertThat(prefilled.get("recipientName").asText()).isEqualTo("收货人");
        assertThat(prefilled.get("recipientPhone").asText()).isEqualTo("13800138000");
        assertThat(prefilled.get("recipientAddress").asText()).isEqualTo("收货地址");
        status(call(get(path), bob, null), 404);

        status(call(put(profilePath), alice, Map.of("basic", basic, "health", Map.of("aiProfileConsent", false))), 200);
        assertThat(body(call(get(path), alice, null)).get("recipientName").isNull()).isTrue();
    }

    @Test
    void healthDefaultsToPrivateAndInternalReadsRequireDelegation() throws Exception {
        assertThat(body(call(get("/api/user/profile"), alice, null)).get("aiProfileConsent").asBoolean()).isFalse();
        String agent = body(call(post("/api/auth/agent-token"), alice, null)).get("token").asText();
        var result = personal(agent, "personalization-context");
        status(result, 200);
        assertThat(body(result).has("profile")).isFalse();
        assertThat(result.getResponse().getHeader("Cache-Control")).isEqualTo("no-store");
        status(personal(alice, "personalization-context"), 403);
        status(call(get("/internal/ai/v1/personalization-context"), agent, null), 401);
    }

    @Test
    void agentCatalogSearchIsBoundedAndStable() throws Exception {
        String agent = body(call(post("/api/auth/agent-token"), alice, null)).get("token").asText();
        var request = get("/internal/ai/v1/medicines").param("limit", "1")
                .header("X-AI-Service-Key", "test-service-key-at-least-32-characters");
        var result = call(request, agent, null);
        status(result, 200);
        assertThat(body(result).size()).isEqualTo(1);
        assertThat(body(result).get(0).get("id").asInt()).isEqualTo(1);
        for (String limit : List.of("0", "21", "-1")) {
            status(call(get("/internal/ai/v1/medicines").param("limit", limit)
                    .header("X-AI-Service-Key", "test-service-key-at-least-32-characters"), agent, null), 400);
        }
        var empty = call(get("/internal/ai/v1/medicines").param("name", "不存在商品")
                .header("X-AI-Service-Key", "test-service-key-at-least-32-characters"), agent, null);
        assertThat(body(empty).isEmpty()).isTrue();
    }

    @Test
    void agentCatalogRejectsInvalidIdsAndFindsMissingProducts() throws Exception {
        String agent = body(call(post("/api/auth/agent-token"), alice, null)).get("token").asText();
        status(personal(agent, "medicines/0"), 400);
        status(personal(agent, "medicines/999999"), 404);
        status(personal(agent, "orders/" + "x".repeat(65)), 400);
    }

    @Test
    void healthConsentWhitelistsContextAndWithdrawalRetainsOwnedProfile() throws Exception {
        status(call(put("/api/user/profile/details"), alice, healthDetails(true)), 200);
        String agent = body(call(post("/api/auth/agent-token"), alice, null)).get("token").asText();
        JsonNode context = body(personal(agent, "personalization-context"));
        assertThat(context.get("enabled").asBoolean()).isTrue();
        assertThat(context.get("revision").asLong()).isEqualTo(1);
        assertThat(context.get("profile").get("bmi").decimalValue()).isEqualByComparingTo("22.2");
        for (String privateField : List.of("name", "userId", "phoneNum", "address", "email", "balance")) {
            assertThat(context.get("profile").has(privateField)).isFalse();
        }
        assertThat(count("profile_consent_events")).isEqualTo(1);
        status(call(put("/api/user/profile/details"), alice, healthDetails(true)), 200);
        assertThat(count("profile_consent_events")).isEqualTo(1);
        status(call(put("/api/user/profile/details"), alice, healthDetails(false)), 200);
        assertThat(count("profile_consent_events")).isEqualTo(2);
        assertThat(body(personal(agent, "personalization-context")).has("profile")).isFalse();
        assertThat(body(personal(agent, "personalization-status")).get("revision").asLong()).isEqualTo(3);
        assertThat(body(call(get("/api/user/profile"), alice, null)).get("heightCm").asInt()).isEqualTo(180);
    }

    @Test
    void healthValidationAndOwnershipDoNotPartiallySave() throws Exception {
        status(call(put("/api/user/profile/details"), bob, healthDetails(true)), 403);
        for (Object height : List.of(0, 261, new BigDecimal("175.55"))) {
            status(call(put("/api/user/profile/details"), alice,
                    Map.of("basic", Map.of("nickname", "must-not-save"),
                            "health", Map.of("heightCm", height, "aiProfileConsent", true))), 400);
        }
        status(call(put("/api/user/profile/details"), alice,
                Map.of("basic", Map.of(), "health", Map.of("heightCm", 180))), 400);
        assertThat(count("profile_consent_events")).isZero();
        assertThat(body(call(get("/api/user/profile"), alice, null)).get("profileContextVersion").asLong()).isZero();
    }

    @Test
    void clearingHealthMetricsWorksAndBasicEditsAdvanceContextRevision() throws Exception {
        status(call(put("/api/user/profile/details"), alice, healthDetails(true)), 200);
        status(call(put("/api/user/profile"), alice, Map.of("nickname", "修改昵称")), 200);
        assertThat(body(call(get("/api/user/profile"), alice, null)).get("profileContextVersion").asLong()).isEqualTo(2);
        status(call(put("/api/user/profile/details"), alice,
                Map.of("basic", Map.of("medicalHistory", List.of()),
                        "health", Map.of("aiProfileConsent", false))), 200);
        JsonNode profile = body(call(get("/api/user/profile"), alice, null));
        assertThat(profile.has("heightCm")).isFalse();
        assertThat(profile.has("weightKg")).isFalse();
        assertThat(profile.get("medicalHistory").isEmpty()).isTrue();
    }

    @Test
    void registrationHashesPasswordAndLoginIssuesOnlyHashedStoredSession() throws Exception {
        status(call(post("/api/auth/register"), null,
                Map.of("userId", "charlie", "password", "Password789")), 200);
        String stored = jdbc.queryForObject("SELECT password FROM users WHERE user_id='charlie'", String.class);
        assertThat(stored).startsWith("$2");
        assertThat(encoder.matches("Password789", stored)).isTrue();
        MvcResult login = call(post("/api/auth/login"), null,
                Map.of("userId", "charlie", "password", "Password789"));
        status(login, 200);
        String token = body(login).get("token").asText();
        assertThat(token).hasSize(43);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM auth_sessions WHERE token_hash=?",
                Integer.class, token)).isZero();
        status(call(get("/api/user/profile"), token, null), 200);
    }

    @Test
    void invalidRegistrationAndOverpostingAreRejected() throws Exception {
        status(call(post("/api/auth/register"), null,
                Map.of("userId", "newuser", "password", "123")), 400);
        status(call(put("/api/user/profile"), alice,
                Map.of("userId", "alice", "balance", 999999)), 400);
        assertThat(balance("alice")).isEqualByComparingTo("100.00");
    }

    @Test
    void duplicateRegistrationReturnsConflict() throws Exception {
        status(call(post("/api/auth/register"), null,
                Map.of("userId", "alice", "password", "Password123")), 409);
    }

    @Test
    void loginFailureLimitPersists() throws Exception {
        for (int i = 0; i < 5; i++) {
            status(call(post("/api/auth/login"), null,
                    Map.of("userId", "alice", "password", "Incorrect123")), 401);
        }
        status(call(post("/api/auth/login"), null,
                Map.of("userId", "alice", "password", "Password123")), 429);
        assertThat(jdbc.queryForObject(
                "SELECT failures FROM security_attempts WHERE attempt_key='login:alice'", Integer.class)).isEqualTo(5);
    }

    @Test
    void unknownAndPlaintextAccountsCannotAuthenticate() throws Exception {
        status(call(post("/api/auth/login"), null,
                Map.of("userId", "unknown", "password", "Password123")), 401);
        jdbc.update("UPDATE users SET password='Password123' WHERE user_id='alice'");
        status(call(post("/api/auth/login"), null,
                Map.of("userId", "alice", "password", "Password123")), 401);
    }

    @Test
    void expiredSessionAndReloginInvalidateOldCredentials() throws Exception {
        jdbc.update("UPDATE auth_sessions SET expires_at=0 WHERE user_id='alice-id'");
        status(call(get("/api/user/profile"), alice, null), 401);
        var login = call(post("/api/auth/login"), null,
                Map.of("userId", "bob", "password", "Password123"));
        status(login, 200);
        status(call(get("/api/user/profile"), bob, null), 401);
        status(call(get("/api/user/profile"), body(login).get("token").asText(), null), 200);
    }

    @Test
    void dataOwnershipCoversProfileWalletTransactionsAndLogout() throws Exception {
        status(call(get("/api/user/profile").param("userId", "bob"), alice, null), 403);
        status(call(put("/api/user/profile"), alice, Map.of("userId", "bob", "nickname", "hacked")), 403);
        status(call(get("/api/wallet/bob"), alice, null), 403);
        status(call(get("/api/transactions").param("userId", "bob"), alice, null), 403);
        status(call(post("/api/auth/logout"), alice, Map.of("userId", "bob")), 403);
        status(call(get("/api/user/profile"), bob, null), 200);
    }

    @Test
    void profileRoundTripDoesNotExposeCredentials() throws Exception {
        status(call(put("/api/user/profile"), alice,
                Map.of("userId", "alice", "nickname", "新昵称", "medicalHistory", List.of("测试记录"))), 200);
        var profile = call(get("/api/user/profile"), alice, null);
        status(profile, 200);
        assertThat(body(profile).get("nickname").asText()).isEqualTo("新昵称");
        assertThat(body(profile).get("medicalHistory").get(0).asText()).isEqualTo("测试记录");
        assertThat(body(profile).has("password")).isFalse();
        assertThat(body(profile).has("walletPassword")).isFalse();
    }

    @Test
    void walletActivationHashesPinAndCannotOverwriteIt() throws Exception {
        jdbc.update("UPDATE users SET wallet_activated=FALSE,walletPassword=NULL WHERE user_id='alice'");
        status(call(post("/api/auth/activate-wallet"), alice,
                Map.of("userId", "bob", "password", "654321")), 403);
        status(call(post("/api/auth/activate-wallet"), alice,
                Map.of("userId", "alice", "password", "abcdef")), 400);
        status(call(post("/api/auth/activate-wallet"), alice,
                Map.of("userId", "alice", "password", "654321")), 200);
        String stored = jdbc.queryForObject("SELECT walletPassword FROM users WHERE user_id='alice'", String.class);
        assertThat(encoder.matches("654321", stored)).isTrue();
        status(call(post("/api/auth/activate-wallet"), alice,
                Map.of("userId", "alice", "password", "111111")), 409);
    }

    @Test
    void userCannotMutateInventory() throws Exception {
        status(call(put("/api/medicines/1/stock").param("quantity", "999"), alice, null), 403);
    }

    @Test
    void paymentPasswordIsRequiredAndFailuresPersistWithoutMoneyMovement() throws Exception {
        Map<String, Object> payload = order();
        payload.remove("walletPassword");
        status(checkout(alice, payload, "missing-password"), 400);
        payload.put("walletPassword", "000000");
        for (int i = 0; i < 5; i++) status(checkout(alice, payload, "wrong-password"), 401);
        payload.put("walletPassword", "123456");
        status(checkout(alice, payload, "locked-password"), 429);
        assertThat(balance("alice")).isEqualByComparingTo("100");
        assertThat(count("orders")).isZero();
        assertThat(count("transactions")).isZero();
    }

    @Test
    void checkoutUsesDatabasePriceAndReturnsAccurateBalanceAndPoints() throws Exception {
        var result = checkout(alice, order(), "checkout-success");
        status(result, 200);
        assertThat(body(result).get("newBalance").decimalValue()).isEqualByComparingTo("78.40");
        assertThat(body(result).get("totalPoints").asInt()).isEqualTo(121);
        assertThat(jdbc.queryForObject("SELECT stock FROM medicines WHERE id=1", Integer.class)).isEqualTo(8);
        assertThat(jdbc.queryForObject("SELECT total_price FROM orders", BigDecimal.class))
                .isEqualByComparingTo("21.60");
        assertThat(count("order_items")).isEqualTo(1);
        assertThat(count("transactions")).isEqualTo(1);
        status(call(get("/api/transactions"), alice, null), 200);
        assertThat(body(call(get("/api/transactions"), alice, null)).size()).isEqualTo(1);
    }

    @Test
    void invalidItemQuantitiesAndDuplicateLinesAreRejected() throws Exception {
        Map<String, Object> payload = order();
        for (Object quantity : List.of(-1, 0, 1.5)) {
            payload.put("items", List.of(Map.of("medicineId", 1, "quantity", quantity)));
            status(checkout(alice, payload, "invalid-quantity"), 400);
        }
        payload.put("items", List.of(Map.of("medicineId", 1, "quantity", 1),
                Map.of("medicineId", 1, "quantity", 1)));
        status(checkout(alice, payload, "duplicate-lines"), 400);
        assertThat(count("orders")).isZero();
    }

    @Test
    void unknownProductInsufficientStockAndBalanceCauseNoPartialWrites() throws Exception {
        Map<String, Object> payload = order();
        payload.put("items", List.of(Map.of("medicineId", 999, "quantity", 1)));
        status(checkout(alice, payload, "unknown-product"), 400);
        payload.put("items", List.of(Map.of("medicineId", 1, "quantity", 11)));
        status(checkout(alice, payload, "out-of-stock"), 400);
        jdbc.update("UPDATE users SET balance=0 WHERE user_id='alice'");
        status(checkout(alice, order(), "insufficient-money"), 400);
        assertThat(count("orders")).isZero();
        assertThat(count("transactions")).isZero();
        assertThat(jdbc.queryForObject("SELECT stock FROM medicines WHERE id=1", Integer.class)).isEqualTo(10);
    }

    @Test
    void clientSuppliedPriceAndMissingIdempotencyKeyAreRejected() throws Exception {
        Map<String, Object> payload = order();
        payload.put("totalPrice", 0.01);
        status(checkout(alice, payload, "forged-price"), 400);
        status(call(post("/api/orders"), alice, order()), 400);
    }

    @Test
    void repeatedCheckoutIsIdempotentAndChangedPayloadConflicts() throws Exception {
        var first = checkout(alice, order(), "same-request-key");
        var repeat = checkout(alice, order(), "same-request-key");
        status(first, 200);
        status(repeat, 200);
        assertThat(body(first).get("orderId")).isEqualTo(body(repeat).get("orderId"));
        Map<String, Object> changed = order();
        changed.put("recipientName", "另一收货人");
        status(checkout(alice, changed, "same-request-key"), 409);
        assertThat(count("orders")).isEqualTo(1);
        assertThat(count("transactions")).isEqualTo(1);
        assertThat(balance("alice")).isEqualByComparingTo("78.40");
    }

    @Test
    void orderLookupAndPhoneSearchNeverExposeOtherUsers() throws Exception {
        var result = checkout(alice, order(), "ownership-order");
        status(result, 200);
        String id = body(result).get("orderId").asText();
        status(call(get("/api/orders/" + id), bob, null), 404);
        status(call(delete("/api/orders/" + id), bob, null), 404);
        status(call(delete("/api/orders/" + id), alice, null), 409);
        status(call(get("/api/orders").param("userId", "alice"), bob, null), 403);
        var search = call(get("/api/orders").param("phone", "13800138000"), bob, null);
        status(search, 200);
        assertThat(body(search).size()).isZero();
    }

    @Test
    void ledgerFailureRollsBackOrderBalanceAndStock() throws Exception {
        jdbc.execute("ALTER TABLE transactions ADD CONSTRAINT reject_purchase CHECK(type <> 'purchase')");
        try {
            status(checkout(alice, order(), "rollback-request"), 500);
            assertThat(balance("alice")).isEqualByComparingTo("100");
            assertThat(count("orders")).isZero();
            assertThat(count("order_items")).isZero();
            assertThat(count("checkout_requests")).isZero();
            assertThat(jdbc.queryForObject("SELECT stock FROM medicines WHERE id=1", Integer.class)).isEqualTo(10);
        } finally {
            jdbc.execute("ALTER TABLE transactions DROP CONSTRAINT reject_purchase");
        }
    }

    @Test
    void negativePointsAreRejectedAndRechargeCannotBeReused() throws Exception {
        status(call(post("/api/wallet/exchange"), alice, Map.of("userId", "alice", "points", -10)), 400);
        status(call(post("/api/wallet/exchange"), alice, Map.of("userId", "bob", "points", 10)), 403);
        status(call(post("/api/wallet/recharge"), alice, Map.of("userId", "bob", "cardId", "CARD-1")), 403);
        status(call(post("/api/wallet/recharge"), alice, Map.of("cardId", "CARD-1")), 200);
        status(call(post("/api/wallet/recharge"), bob, Map.of("cardId", "CARD-1")), 400);
        assertThat(balance("alice")).isEqualByComparingTo("150");
        assertThat(balance("bob")).isEqualByComparingTo("100");
        status(call(post("/api/wallet/exchange"), alice, Map.of("points", 10)), 200);
        assertThat(balance("alice")).isEqualByComparingTo("151");
    }

    @Test
    void concurrentPurchasesDoNotOversellTheLastItem() throws Exception {
        jdbc.update("UPDATE medicines SET stock=1 WHERE id=1");
        Map<String, Object> a = order();
        a.put("items", List.of(Map.of("medicineId", 1, "quantity", 1)));
        Map<String, Object> b = new HashMap<>(a);
        b.put("userId", "bob");
        List<Integer> statuses = parallel(
                () -> checkout(alice, a, "parallel-alice").getResponse().getStatus(),
                () -> checkout(bob, b, "parallel-bob").getResponse().getStatus());
        assertThat(statuses).containsExactlyInAnyOrder(200, 400);
        assertThat(count("orders")).isEqualTo(1);
        assertThat(count("transactions")).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT stock FROM medicines WHERE id=1", Integer.class)).isZero();
        assertThat(balance("alice").add(balance("bob"))).isEqualByComparingTo("189.20");
    }

    @Test
    void concurrentCardRedemptionCreditsExactlyOneUser() throws Exception {
        List<Integer> statuses = parallel(
                () -> call(post("/api/wallet/recharge"), alice, Map.of("cardId", "CARD-1"))
                        .getResponse().getStatus(),
                () -> call(post("/api/wallet/recharge"), bob, Map.of("cardId", "CARD-1"))
                        .getResponse().getStatus());
        assertThat(statuses).containsExactlyInAnyOrder(200, 400);
        assertThat(balance("alice").add(balance("bob"))).isEqualByComparingTo("250");
        assertThat(count("transactions")).isEqualTo(1);
    }

    @Test
    void agentNeedsBothServiceIdentityAndDelegationAndCannotPay() throws Exception {
        var delegated = call(post("/api/auth/agent-token"), alice, null);
        status(delegated, 200);
        String token = body(delegated).get("token").asText();
        assertThat(body(delegated).get("scope").asText()).isEqualTo("AGENT_READ");
        status(call(get("/internal/ai/v1/me"), token, null), 401);
        status(call(get("/internal/ai/v1/me").header("X-AI-Service-Key", "wrong-key"), token, null), 401);
        String key = "test-service-key-at-least-32-characters";
        status(call(get("/internal/ai/v1/me").header("X-AI-Service-Key", key), alice, null), 403);
        var me = call(get("/internal/ai/v1/me").header("X-AI-Service-Key", key), token, null);
        status(me, 200);
        assertThat(body(me).get("userId").asText()).isEqualTo("alice");
        status(call(get("/internal/ai/v1/medicines").header("X-AI-Service-Key", key), token, null), 200);
        status(checkout(token, order(), "agent-payment"), 403);
        status(call(post("/api/auth/agent-token"), token, null), 403);
        status(call(post("/api/auth/logout"), alice, null), 200);
        status(call(get("/internal/ai/v1/me").header("X-AI-Service-Key", key), token, null), 401);
        status(call(get("/api/user/profile"), alice, null), 401);
    }

    @Test
    void delegatedOrderIsScopedAndDoesNotIncludeRecipientPii() throws Exception {
        var result = checkout(alice, order(), "agent-order-check");
        String id = body(result).get("orderId").asText();
        String agentA = body(call(post("/api/auth/agent-token"), alice, null)).get("token").asText();
        String agentB = body(call(post("/api/auth/agent-token"), bob, null)).get("token").asText();
        String key = "test-service-key-at-least-32-characters";
        var response = call(get("/internal/ai/v1/orders/" + id).header("X-AI-Service-Key", key), agentA, null);
        status(response, 200);
        assertThat(body(response).has("recipientPhone")).isFalse();
        assertThat(body(response).has("recipientAddress")).isFalse();
        status(call(get("/internal/ai/v1/orders/" + id).header("X-AI-Service-Key", key), agentB, null), 404);
        jdbc.update("UPDATE auth_sessions SET expires_at=0 WHERE scope='AGENT_READ'");
        status(call(get("/internal/ai/v1/me").header("X-AI-Service-Key", key), agentA, null), 401);
    }

    @Test
    void legacyMigrationHashesPasswordsAndInvalidatesSessionsWithoutRehashing() throws Exception {
        jdbc.update("UPDATE users SET password='123456',walletPassword='654321' WHERE user_id='alice'");
        jdbc.update("UPDATE users SET walletPassword='invalid-pin' WHERE user_id='bob'");
        var migration = new com.example.mybatisplus.security.LegacyPasswordMigration(userMapper, encoder, jdbc);
        var transaction = new org.springframework.transaction.support.TransactionTemplate(transactionManager);
        transaction.executeWithoutResult(ignored -> migration.run());
        String stored = jdbc.queryForObject("SELECT password FROM users WHERE user_id='alice'", String.class);
        String storedPin = jdbc.queryForObject("SELECT walletPassword FROM users WHERE user_id='alice'", String.class);
        assertThat(encoder.matches("123456", stored)).isTrue();
        assertThat(encoder.matches("654321", storedPin)).isTrue();
        assertThat(jdbc.queryForObject(
                "SELECT wallet_activated FROM users WHERE user_id='bob'", Boolean.class)).isFalse();
        assertThat(count("auth_sessions")).isZero();
        transaction.executeWithoutResult(ignored -> migration.run());
        assertThat(jdbc.queryForObject("SELECT password FROM users WHERE user_id='alice'", String.class))
                .isEqualTo(stored);
        status(call(post("/api/auth/login"), null, Map.of("userId", "alice", "password", "123456")), 200);
    }

    @Test
    void migrationFailureRollsBackAndMultibytePasswordsAreValidated() throws Exception {
        jdbc.update("UPDATE users SET password='old-password' WHERE user_id='alice'");
        jdbc.update("UPDATE users SET password=? WHERE user_id='bob'", "长".repeat(30));
        var migration = new com.example.mybatisplus.security.LegacyPasswordMigration(userMapper, encoder, jdbc);
        var transaction = new org.springframework.transaction.support.TransactionTemplate(transactionManager);
        org.assertj.core.api.Assertions.assertThatThrownBy(
                () -> transaction.executeWithoutResult(ignored -> migration.run()))
                .isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject("SELECT password FROM users WHERE user_id='alice'", String.class))
                .isEqualTo("old-password");
        assertThat(count("auth_sessions")).isEqualTo(2);
        status(call(post("/api/auth/register"), null,
                Map.of("userId", "unicodeuser", "password", "长".repeat(30))), 400);
        status(call(post("/api/auth/login"), null,
                Map.of("userId", "bob", "password", "长".repeat(30))), 401);
    }

    @Test
    void concurrentRetriesOfTheSameCheckoutChargeOnce() throws Exception {
        List<Integer> statuses = parallel(
                () -> checkout(alice, order(), "concurrent-retry").getResponse().getStatus(),
                () -> checkout(alice, order(), "concurrent-retry").getResponse().getStatus());
        assertThat(statuses).containsExactly(200, 200);
        assertThat(count("orders")).isEqualTo(1);
        assertThat(count("transactions")).isEqualTo(1);
        assertThat(balance("alice")).isEqualByComparingTo("78.40");
    }

    @Test
    void invalidRoutesAndParametersReturnControlledErrors() throws Exception {
        status(call(get("/api/orders/not-real"), alice, null), 404);
        status(call(get("/api/missing"), alice, null), 404);
        status(call(get("/stream"), alice, null), 403);
        String agent = body(call(post("/api/auth/agent-token"), alice, null)).get("token").asText();
        String key = "test-service-key-at-least-32-characters";
        status(call(get("/internal/ai/v1/medicines/not-a-number")
                .header("X-AI-Service-Key", key), agent, null), 400);
    }

    @Test
    void localBrowserOriginsAreAcceptedButForeignOriginsAreRejected() throws Exception {
        status(call(post("/api/auth/login").header("Origin", "http://127.0.0.1:3000"),
                null, Map.of()), 400);
        status(call(get("/api/user/profile").header("Origin", "http://127.0.0.1:3000"),
                alice, null), 200);
        status(call(post("/api/auth/login").header("Origin", "https://untrusted.example"),
                null, Map.of()), 403);
    }

    private List<Integer> parallel(Callable<Integer> first, Callable<Integer> second) throws Exception {
        ExecutorService executor = Executors.newFixedThreadPool(2);
        CountDownLatch start = new CountDownLatch(1);
        try {
            Future<Integer> a = executor.submit(() -> { start.await(); return first.call(); });
            Future<Integer> b = executor.submit(() -> { start.await(); return second.call(); });
            start.countDown();
            return List.of(a.get(30, TimeUnit.SECONDS), b.get(30, TimeUnit.SECONDS));
        } finally {
            executor.shutdownNow();
        }
    }
}
