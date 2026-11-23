package com.example.mybatisplus;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/** Same payment scenarios against a disposable, privilege-isolated real MySQL database. */
@EnabledIfEnvironmentVariable(named="M51_MYSQL_TEST", matches="true")
class CommerceMySqlTests extends CommerceBusinessTests {
    @DynamicPropertySource
    static void mysql(DynamicPropertyRegistry registry) throws Exception {
        JsonNode config = new ObjectMapper().readTree(Files.readString(Path.of(System.getenv("M51_MYSQL_CONFIG"))));
        if (!config.get("database").asText().matches("DeepseekDoc_M51_Test_[0-9a-f]{10}")) throw new IllegalStateException("Unsafe test database");
        if (!config.get("username").asText().matches("m51test_[0-9a-f]{10}")) throw new IllegalStateException("Unsafe test user");
        registry.add("spring.datasource.url", () -> config.get("url").asText());
        registry.add("spring.datasource.username", () -> config.get("username").asText());
        registry.add("spring.datasource.password", () -> config.get("password").asText());
        registry.add("spring.datasource.driver-class-name", () -> "com.mysql.cj.jdbc.Driver");
        registry.add("spring.sql.init.mode", () -> "never");
    }
    @BeforeAll void ownedSchema() {
        String name = db.queryForObject("SELECT DATABASE()",String.class);
        if (!name.matches("(?i)DeepseekDoc_M51_Test_[0-9a-f]{10}")
                || !"m51-isolated-mysql-v1".equals(db.queryForObject("SELECT marker FROM m51_test_environment",String.class))) {
            throw new IllegalStateException("Refusing payment tests on a non-owned database");
        }
    }
}
