package com.example.mybatisplus.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.example.mybatisplus.dto.Requests;
import com.example.mybatisplus.entity.Transaction;
import com.example.mybatisplus.entity.User;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.mapper.TransactionMapper;
import com.example.mybatisplus.mapper.UserMapper;
import com.example.mybatisplus.security.CredentialVerifier;
import com.example.mybatisplus.security.SessionService;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class UserService {
    private final UserMapper users;
    private final TransactionMapper transactions;
    private final PasswordEncoder encoder;
    private final SessionService sessions;
    private final CredentialVerifier verifier;
    private final JdbcTemplate jdbc;

    public UserService(UserMapper users, TransactionMapper transactions, PasswordEncoder encoder,
                       SessionService sessions, CredentialVerifier verifier, JdbcTemplate jdbc) {
        this.users = users;
        this.transactions = transactions;
        this.encoder = encoder;
        this.sessions = sessions;
        this.verifier = verifier;
        this.jdbc = jdbc;
    }

    public Map<String, Object> register(String username, String password) {
        if (password.getBytes(StandardCharsets.UTF_8).length > 72) {
            throw new ApiException("密码UTF-8编码不能超过72字节");
        }
        if (users.selectCount(new QueryWrapper<User>().eq("user_id", username)) > 0) {
            throw new ApiException(HttpStatus.CONFLICT, "USER_EXISTS", "用户名已存在");
        }
        User user = new User();
        user.setUserId(username);
        user.setPassword(encoder.encode(password));
        user.setBalance(BigDecimal.ZERO);
        user.setPoints(0);
        user.setWalletActivated(false);
        user.setAiProfileConsent(false);
        user.setProfileContextVersion(0L);
        user.setProfileConsentUpdatedAt(0L);
        users.insert(user);
        return Map.of("success", true);
    }

    public Map<String, Object> login(String username, String password) {
        User user = verifier.verify(username, password, false);
        Map<String, Object> response = new HashMap<>(sessions.create(user.getId(), user.getUserId()));
        response.put("walletActivated", Boolean.TRUE.equals(user.getWalletActivated()));
        return response;
    }

    public User getUser(String username) {
        User user = users.selectOne(new QueryWrapper<User>().eq("user_id", username));
        if (user == null) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "用户不存在");
        return user;
    }

    private User lockUser(String username) {
        User user = users.selectOne(new QueryWrapper<User>().eq("user_id", username).last("FOR UPDATE"));
        if (user == null) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "用户不存在");
        return user;
    }

    @Transactional
    public Map<String, Object> activateWallet(String username, String password) {
        User user = lockUser(username);
        if (Boolean.TRUE.equals(user.getWalletActivated())) {
            throw new ApiException(HttpStatus.CONFLICT, "WALLET_ALREADY_ACTIVE", "钱包已激活，不能覆盖支付密码");
        }
        users.update(null, new UpdateWrapper<User>().eq("id", user.getId())
                .set("wallet_activated", true).set("walletPassword", encoder.encode(password))
                .set("health_token", null));
        return Map.of("healthToken", "wallet-active", "walletActivated", true);
    }

    public Map<String, Object> getUserProfile(String username) {
        User user = getUser(username);
        Map<String, Object> profile = new HashMap<>();
        profile.put("userId", user.getUserId());
        profile.put("nickname", user.getNickname());
        profile.put("email", user.getEmail());
        profile.put("name", user.getName());
        profile.put("age", user.getAge());
        profile.put("gender", user.getGender());
        profile.put("birthday", user.getBirthday());
        profile.put("phoneNum", user.getPhoneNum());
        profile.put("address", user.getAddress());
        profile.put("medicalHistory", user.getMedicalHistory());
        profile.put("heightCm", user.getHeightCm());
        profile.put("weightKg", user.getWeightKg());
        profile.put("medicalHistoryText", user.getMedicalHistoryText());
        profile.put("allergiesText", user.getAllergiesText());
        profile.put("medicationsText", user.getMedicationsText());
        profile.put("lifestyleText", user.getLifestyleText());
        profile.put("healthNotes", user.getHealthNotes());
        profile.put("aiProfileConsent", Boolean.TRUE.equals(user.getAiProfileConsent()));
        profile.put("profileContextVersion", user.getProfileContextVersion());
        profile.put("profileConsentUpdatedAt", user.getProfileConsentUpdatedAt());
        profile.put("walletActivated", Boolean.TRUE.equals(user.getWalletActivated()));
        profile.entrySet().removeIf(entry -> entry.getValue() == null);
        return profile;
    }

    private UpdateWrapper<User> basic(User user, Requests.Profile profile, boolean full) {
        var update = new UpdateWrapper<User>().eq("id", user.getId());
        if (full || profile.nickname() != null) update.set("nickname", profile.nickname());
        if (full || profile.email() != null) update.set("email", profile.email());
        if (full || profile.name() != null) update.set("name", profile.name());
        if (full || profile.age() != null) update.set("age", profile.age());
        if (full || profile.gender() != null) update.set("gender", profile.gender());
        if (full || profile.birthday() != null) update.set("birthday", profile.birthday());
        if (full || profile.phoneNum() != null) update.set("phone_num", profile.phoneNum());
        if (full || profile.address() != null) update.set("address", profile.address());
        if (full || profile.medicalHistory() != null) {
            // Use the declared JSON type handler rather than serializing user data into SQL.
            User patch = new User();
            patch.setId(user.getId());
            patch.setMedicalHistory(profile.medicalHistory() == null ? List.of() : profile.medicalHistory());
            users.updateById(patch);
        }
        return update;
    }

    @Transactional
    public void updateUserProfile(String username, Requests.Profile profile) {
        User user = lockUser(username);
        var update = basic(user, profile, false);
        update.set("profile_context_version", Math.addExact(user.getProfileContextVersion(), 1L));
        users.update(null, update);
    }

    @Transactional
    public Map<String, Object> updateProfileDetails(String username, Requests.ProfileDetails details) {
        User user = lockUser(username);
        Requests.HealthDetails health = details.health();
        long revision = Math.addExact(user.getProfileContextVersion(), 1L);
        var update = basic(user, details.basic(), true)
                .set("height_cm", health.heightCm()).set("weight_kg", health.weightKg())
                .set("medical_history_text", clean(health.medicalHistoryText()))
                .set("allergies_text", clean(health.allergiesText()))
                .set("medications_text", clean(health.medicationsText()))
                .set("lifestyle_text", clean(health.lifestyleText()))
                .set("health_notes", clean(health.healthNotes()))
                .set("ai_profile_consent", health.aiProfileConsent())
                .set("profile_context_version", revision);
        if (Boolean.TRUE.equals(user.getAiProfileConsent()) != health.aiProfileConsent()) {
            long changedAt = System.currentTimeMillis();
            update.set("profile_consent_updated_at", changedAt);
            jdbc.update("INSERT INTO profile_consent_events VALUES (?,?,?,?,?)",
                    UUID.randomUUID().toString(), user.getId(), health.aiProfileConsent(), revision, changedAt);
        }
        users.update(null, update);
        return Map.of("saved", true, "profileContextVersion", revision,
                "aiProfileConsent", health.aiProfileConsent());
    }

    private String clean(String value) { return value == null ? "" : value.strip(); }

    public Map<String, Object> personalizationStatus(String username) {
        User user = users.selectOne(new QueryWrapper<User>()
                .select("ai_profile_consent", "profile_context_version")
                .eq("user_id", username));
        return Map.of("enabled", Boolean.TRUE.equals(user.getAiProfileConsent()),
                "revision", user.getProfileContextVersion());
    }

    public Map<String, Object> personalizationContext(String username) {
        User user = getUser(username);
        boolean enabled = Boolean.TRUE.equals(user.getAiProfileConsent());
        Map<String, Object> result = new HashMap<>();
        result.put("enabled", enabled);
        result.put("revision", user.getProfileContextVersion());
        if (!enabled) return result;
        Map<String, Object> health = new LinkedHashMap<>();
        health.put("age", user.getAge());
        health.put("gender", user.getGender());
        health.put("heightCm", user.getHeightCm());
        health.put("weightKg", user.getWeightKg());
        health.put("medicalHistory", user.getMedicalHistory());
        health.put("medicalHistoryText", user.getMedicalHistoryText());
        health.put("allergiesText", user.getAllergiesText());
        health.put("medicationsText", user.getMedicationsText());
        health.put("lifestyleText", user.getLifestyleText());
        health.put("healthNotes", user.getHealthNotes());
        if (user.getHeightCm() != null && user.getWeightKg() != null) {
            BigDecimal metres = user.getHeightCm().divide(BigDecimal.valueOf(100));
            health.put("bmi", user.getWeightKg().divide(metres.pow(2), 1, RoundingMode.HALF_UP));
        }
        health.entrySet().removeIf(entry -> entry.getValue() == null
                || entry.getValue() instanceof String text && text.isBlank()
                || entry.getValue() instanceof List<?> list && list.isEmpty());
        result.put("profile", health);
        return result;
    }

    public Map<String, Object> getWalletData(String username) {
        User user = getUser(username);
        var ledger = transactions.selectList(
                new QueryWrapper<Transaction>().eq("user_id", user.getId()).orderByDesc("created_at"));
        return Map.of("balance", user.getBalance(), "points", user.getPoints(),
                "walletActivated", Boolean.TRUE.equals(user.getWalletActivated()), "transactions", ledger);
    }
}
