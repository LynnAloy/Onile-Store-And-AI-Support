package com.example.mybatisplus.security;

import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.example.mybatisplus.entity.User;
import com.example.mybatisplus.mapper.UserMapper;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
@ConditionalOnProperty(name = "security.migrate-legacy-passwords", havingValue = "true")
public class LegacyPasswordMigration implements CommandLineRunner {
    private final UserMapper users;
    private final PasswordEncoder encoder;
    private final JdbcTemplate jdbc;

    public LegacyPasswordMigration(UserMapper users, PasswordEncoder encoder, JdbcTemplate jdbc) {
        this.users = users;
        this.encoder = encoder;
        this.jdbc = jdbc;
    }

    @Override
    @Transactional
    public void run(String... args) {
        for (User user : users.selectList(null)) {
            var update = new UpdateWrapper<User>().eq("id", user.getId())
                    .set("token", null).set("health_token", null);
            if (user.getPassword() != null && !user.getPassword().matches("\\$2[aby]\\$.*")) {
                if (user.getPassword().getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 72) {
                    throw new IllegalStateException("Legacy password exceeds BCrypt limit; reset it before migration");
                }
                update.set("password", encoder.encode(user.getPassword()));
            }
            String pin = user.getWalletPassword();
            if (pin != null && !pin.matches("\\$2[aby]\\$.*")) {
                if (pin.matches("[0-9]{6}")) {
                    update.set("walletPassword", encoder.encode(pin));
                } else {
                    update.set("walletPassword", null).set("wallet_activated", false);
                }
            }
            users.update(null, update);
        }
        jdbc.update("DELETE FROM auth_sessions");
        jdbc.update("DELETE FROM security_attempts");
    }
}
