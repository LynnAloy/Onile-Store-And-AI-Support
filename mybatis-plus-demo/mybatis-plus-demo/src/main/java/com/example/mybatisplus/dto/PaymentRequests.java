package com.example.mybatisplus.dto;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.databind.DeserializationContext;
import com.fasterxml.jackson.databind.JsonDeserializer;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import jakarta.validation.constraints.*;
import java.io.IOException;

public final class PaymentRequests {
    private PaymentRequests() {}
    public record Version(@NotNull @Min(1) @Max(9007199254740991L) Long expectedVersion) {}
    public record Authorize(@NotNull @Min(1) @Max(9007199254740991L) Long expectedVersion,
            @NotNull @Size(min=1,max=72) @JsonDeserialize(using=PasswordString.class) String password) {}
    public static class PasswordString extends JsonDeserializer<String> {
        @Override public String deserialize(JsonParser p, DeserializationContext c) throws IOException {
            if (!p.hasToken(JsonToken.VALUE_STRING)) return c.reportInputMismatch(String.class, "String required");
            return p.getText();
        }
    }
}
