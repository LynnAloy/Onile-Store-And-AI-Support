package com.example.mybatisplus.dto;

import java.util.List;
import java.math.BigDecimal;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;

public final class Requests {
    private Requests() {}

    public record Credentials(
            @NotBlank @Pattern(regexp = "[A-Za-z0-9_-]{3,40}") String userId,
            @NotBlank @Size(min = 8, max = 64) String password) {}

    public record WalletSetup(String userId,
            @NotBlank @Pattern(regexp = "[0-9]{6}") String password) {}

    // Existing accounts may have shorter passwords; new registration remains >= 8 characters.
    public record Login(
            @NotBlank @Pattern(regexp = "[A-Za-z0-9_-]{3,40}") String userId,
            @NotBlank @Size(max = 64) String password) {}

    public record Recharge(String userId, @NotBlank @Size(max = 20) String cardId) {}

    public record Exchange(String userId, @NotNull @Min(1) @Max(1000000) Integer points) {}

    public record Logout(String userId) {}

    public record Profile(
            String userId,
            @Size(max = 50) String nickname,
            @Email @Size(max = 100) String email,
            @Size(max = 15) String name,
            @Min(0) @Max(120) Integer age,
            @Pattern(regexp = "Male|Female") String gender,
            @Size(max = 30) String birthday,
            @Pattern(regexp = "^$|1[3-9][0-9]{9}") String phoneNum,
            @Size(max = 50) String address,
            @Size(max = 30) List<@NotBlank @Size(max = 100) String> medicalHistory) {}

    public record HealthDetails(
            @DecimalMin("30") @DecimalMax("260") @Digits(integer = 3, fraction = 1) BigDecimal heightCm,
            @DecimalMin("1") @DecimalMax("500") @Digits(integer = 3, fraction = 1) BigDecimal weightKg,
            @Size(max = 2000) String medicalHistoryText,
            @Size(max = 1000) String allergiesText,
            @Size(max = 1000) String medicationsText,
            @Size(max = 1000) String lifestyleText,
            @Size(max = 2000) String healthNotes,
            @NotNull Boolean aiProfileConsent) {}

    public record ProfileDetails(
            @NotNull @Valid Profile basic,
            @NotNull @Valid HealthDetails health) {}
}
