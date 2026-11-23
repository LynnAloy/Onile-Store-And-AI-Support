package com.example.mybatisplus.security;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.example.mybatisplus.entity.User;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.mapper.UserMapper;
import java.time.Instant;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class CredentialVerifier {
    private final JdbcTemplate jdbc;
    private final UserMapper users;
    private final PasswordEncoder encoder;
    private final TransactionTemplate transaction;
    private final String dummy;

    public CredentialVerifier(JdbcTemplate jdbc, UserMapper users, PasswordEncoder encoder,
                              PlatformTransactionManager manager) {
        this.jdbc = jdbc;
        this.users = users;
        this.encoder = encoder;
        this.dummy = encoder.encode("unmatchable-dummy-password");
        this.transaction = new TransactionTemplate(manager);
        this.transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    private record Result(User user, ApiException error) {}

    public User verify(String username, String password, boolean payment) {
        Result result = transaction.execute(status -> {
            String key = (payment ? "pay:" : "login:") + username;
            jdbc.update("INSERT INTO security_attempts(attempt_key,failures,locked_until) "
                    + "VALUES (?,0,0) ON DUPLICATE KEY UPDATE attempt_key=attempt_key", key);
            var attempt = jdbc.queryForMap(
                    "SELECT failures,locked_until FROM security_attempts WHERE attempt_key=? FOR UPDATE", key);
            long now = Instant.now().getEpochSecond();
            long locked = ((Number) attempt.get("locked_until")).longValue();
            if (locked > now) {
                return new Result(null, new ApiException(HttpStatus.TOO_MANY_REQUESTS,
                        "RATE_LIMITED", "验证失败次数过多，请15分钟后重试"));
            }
            User user = users.selectOne(new QueryWrapper<User>().eq("user_id", username));
            String hash = user == null ? null : payment ? user.getWalletPassword() : user.getPassword();
            boolean encoded = hash != null && hash.matches("\\$2[aby]\\$.*");
            boolean lengthValid = password.getBytes(java.nio.charset.StandardCharsets.UTF_8).length <= 72;
            boolean matches = encoder.matches(lengthValid ? password : "invalid-password-length",
                    encoded ? hash : dummy) && lengthValid;
            boolean ready = !payment || user != null && Boolean.TRUE.equals(user.getWalletActivated());
            if (!encoded || !matches || !ready) {
                int failures = locked != 0 ? 1 : ((Number) attempt.get("failures")).intValue() + 1;
                long until = failures >= 5 ? now + 900 : 0;
                jdbc.update("UPDATE security_attempts SET failures=?,locked_until=? WHERE attempt_key=?",
                        failures, until, key);
                return new Result(null, new ApiException(HttpStatus.UNAUTHORIZED,
                        payment ? "PAYMENT_VERIFICATION_FAILED" : "INVALID_CREDENTIALS",
                        payment ? "支付密码错误或钱包未激活" : "用户名或密码错误"));
            }
            jdbc.update("UPDATE security_attempts SET failures=0,locked_until=0 WHERE attempt_key=?", key);
            return new Result(user, null);
        });
        // Throw after committing: failed-attempt counters must survive business rollback.
        if (result.error() != null) throw result.error();
        return result.user();
    }
}
