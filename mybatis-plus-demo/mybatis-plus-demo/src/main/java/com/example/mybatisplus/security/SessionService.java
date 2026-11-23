package com.example.mybatisplus.security;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class SessionService {
    private final JdbcTemplate jdbc;
    private final long ttl;
    private final SecureRandom random = new SecureRandom();

    public SessionService(JdbcTemplate jdbc, @Value("${security.session-ttl-seconds:7200}") long ttl) {
        this.jdbc = jdbc;
        this.ttl = ttl;
    }

    public static String digest(String value) {
        try {
            byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (java.security.NoSuchAlgorithmException ex) {
            throw new IllegalStateException(ex);
        }
    }

    public long now() { return Instant.now().getEpochSecond(); }

    @Transactional
    public Map<String, Object> create(String userId, String username) {
        // Serialize login/logout/delegation on the same account.
        jdbc.queryForObject("SELECT id FROM users WHERE id = ? FOR UPDATE", String.class, userId);
        jdbc.update("DELETE FROM auth_sessions WHERE user_id = ?", userId);
        return issue(userId, username, "USER", null, now() + ttl);
    }

    private Map<String, Object> issue(String userId, String username, String scope,
                                     String parentHash, long expires) {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        jdbc.update("INSERT INTO auth_sessions(token_hash,user_id,scope,parent_hash,expires_at) "
                + "VALUES (?,?,?,?,?)", digest(token), userId, scope, parentHash, expires);
        return Map.of("token", token, "userId", username, "expiresAt", expires, "scope", scope);
    }

    public Actor resolve(String raw) {
        if (raw == null || !raw.matches("[A-Za-z0-9_-]{43}")) return null;
        List<Actor> result = jdbc.query(
                "SELECT s.user_id AS account_id,u.user_id AS username,s.scope,s.token_hash "
                + "FROM auth_sessions s JOIN users u ON u.id=s.user_id "
                + "WHERE s.token_hash=? AND s.expires_at>? AND "
                + "(s.scope='USER' OR EXISTS (SELECT 1 FROM auth_sessions p "
                + "WHERE p.token_hash=s.parent_hash AND p.scope='USER' AND p.expires_at>?))",
                (rs, row) -> new Actor(rs.getString("account_id"), rs.getString("username"),
                        rs.getString("scope"), rs.getString("token_hash")),
                digest(raw), now(), now());
        return result.isEmpty() ? null : result.getFirst();
    }

    @Transactional
    public Map<String, Object> delegate(Actor actor) {
        return delegateScope(actor, "AGENT_READ");
    }

    @Transactional
    public Map<String, Object> delegateOrder(Actor actor) {
        return delegateScope(actor, "AGENT_ORDER_PREPARE");
    }

    private Map<String, Object> delegateScope(Actor actor, String scope) {
        jdbc.queryForObject("SELECT id FROM users WHERE id=? FOR UPDATE", String.class, actor.id());
        Long parentExpiry = jdbc.queryForObject(
                "SELECT expires_at FROM auth_sessions WHERE token_hash=? AND scope='USER'",
                Long.class, actor.sessionHash());
        if (parentExpiry == null || parentExpiry <= now()) {
            throw new com.example.mybatisplus.exception.ApiException(
                    org.springframework.http.HttpStatus.UNAUTHORIZED, "UNAUTHORIZED", "登录已失效");
        }
        return issue(actor.id(), actor.username(), scope, actor.sessionHash(),
                Math.min(parentExpiry, now() + 300));
    }

    @Transactional
    public void logout(Actor actor) {
        jdbc.queryForObject("SELECT id FROM users WHERE id=? FOR UPDATE", String.class, actor.id());
        jdbc.update("DELETE FROM auth_sessions WHERE user_id=? AND parent_hash=?", actor.id(), actor.sessionHash());
        jdbc.update("DELETE FROM auth_sessions WHERE user_id=? AND token_hash=?", actor.id(), actor.sessionHash());
    }
}
