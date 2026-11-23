package com.example.mybatisplus.controller;

import com.example.mybatisplus.security.CurrentUser;
import com.example.mybatisplus.service.CommerceAccess;
import com.example.mybatisplus.exception.ApiException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.net.URI;
import java.nio.file.*;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
public class ModelConfigController {
    private final CommerceAccess access;
    private final CurrentUser current;
    private final ObjectMapper json;
    private final Path path;
    private final String model;
    private final String endpoint;
    public record Config(@NotNull @Min(0) Long expectedVersion,
            @NotBlank @Size(max=100) String model, @NotBlank @Size(max=500) String endpoint,
            @Pattern(regexp="ollama|openai") String protocol, @Size(max=500) String apiKey, Boolean clearApiKey) {
        public Config(Long version,String model,String endpoint) { this(version,model,endpoint,"ollama",null,false); }
        @Override public String toString() { return "ModelConfig[credentials redacted]"; }
    }
    public ModelConfigController(CommerceAccess access,CurrentUser current,ObjectMapper json,
            @Value("${AI_CONFIG_PATH:../../.local-run/model-config.json}") String path,
            @Value("${OLLAMA_MODEL:deepseek-r1:1.5b}") String model,
            @Value("${OLLAMA_BASE_URL:http://127.0.0.1:11434}") String endpoint) {
        this.access=access; this.current=current; this.json=json;
        this.path=Path.of(path).toAbsolutePath().normalize(); this.model=model; this.endpoint=endpoint;
    }
    private Map<String,Object> read() throws java.io.IOException {
        if (!Files.exists(path)) return Map.of("version",0,"model",model,"endpoint",endpoint,"protocol","ollama");
        return json.readValue(Files.readString(path),new com.fasterxml.jackson.core.type.TypeReference<>() {});
    }
    private Map<String,Object> publicConfig(Map<String,Object> stored) {
        var result=new java.util.LinkedHashMap<String,Object>(stored);
        Object secret=result.remove("apiKey");
        result.put("hasApiKey",secret instanceof String text && !text.isBlank());
        result.putIfAbsent("protocol","ollama");
        return result;
    }
    public static String validateEndpoint(String value) {
        try {
            URI uri=URI.create(value.trim());
            String host=uri.getHost();
            boolean loopback=host!=null && java.util.Set.of("localhost","127.0.0.1","[::1]","::1").contains(host);
            if (host==null || uri.getUserInfo()!=null || uri.getQuery()!=null || uri.getFragment()!=null
                    || !("https".equals(uri.getScheme()) || "http".equals(uri.getScheme()) && loopback)) throw new IllegalArgumentException();
            return value.trim().replaceAll("/+$","");
        } catch (IllegalArgumentException ex) { throw new ApiException("endpoint须为HTTPS地址或本机HTTP地址，不能包含密码、查询参数或片段"); }
    }
    @GetMapping("/api/admin/ai-config") public synchronized ResponseEntity<?> get(@RequestHeader("Authorization") String auth) throws java.io.IOException {
        access.requireAdmin(current.actor(),auth.substring(7));
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(publicConfig(read()));
    }
    @PutMapping("/api/admin/ai-config") public synchronized ResponseEntity<?> put(@RequestHeader("Authorization") String auth,
            @Valid @RequestBody Config body) throws java.io.IOException {
        access.requireAdmin(current.actor(),auth.substring(7));
        var old=read();
        if (((Number)old.get("version")).longValue()!=body.expectedVersion())
            throw new ApiException(HttpStatus.CONFLICT,"VERSION_CONFLICT","模型配置已变化，请刷新后重试");
        String target=validateEndpoint(body.endpoint());
        var config=new java.util.LinkedHashMap<String,Object>(Map.of("version",body.expectedVersion()+1,"model",body.model().trim(),"endpoint",target,
                "protocol",body.protocol()==null ? "ollama" : body.protocol(),"updatedBy",current.actor().username(),"updatedAt",java.time.Instant.now().getEpochSecond()));
        String key=body.apiKey()==null ? "" : body.apiKey().trim();
        if (key.contains("\r") || key.contains("\n")) throw new ApiException("API Key格式不合法");
        boolean sameTarget=target.equals(old.get("endpoint")) && config.get("protocol").equals(old.getOrDefault("protocol","ollama"));
        if (!Boolean.TRUE.equals(body.clearApiKey())) {
            if (!key.isBlank()) config.put("apiKey",key);
            else if (sameTarget && old.containsKey("apiKey")) config.put("apiKey",old.get("apiKey"));
        }
        Files.createDirectories(path.getParent());
        Path temp=Files.createTempFile(path.getParent(),"model-config-",".tmp");
        try {
            Files.writeString(temp,json.writeValueAsString(config));
            access.requireAdmin(current.actor(),auth.substring(7));
            Files.move(temp,path,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(temp); }
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(publicConfig(config));
    }
}
