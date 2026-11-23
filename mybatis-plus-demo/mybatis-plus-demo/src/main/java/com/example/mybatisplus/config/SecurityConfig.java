package com.example.mybatisplus.config;

import com.example.mybatisplus.security.BearerFilter;
import com.example.mybatisplus.security.SessionService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
public class SecurityConfig {
    @Bean
    public org.springframework.security.crypto.password.PasswordEncoder passwordEncoder() {
        return new org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder(12);
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http, SessionService sessions,
            @Value("${security.ai-service-key:}") String serviceKey) throws Exception {
        http.cors(Customizer.withDefaults()).csrf(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable).httpBasic(AbstractHttpConfigurer::disable)
                .logout(AbstractHttpConfigurer::disable)
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(a -> a
                        .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                        .requestMatchers(HttpMethod.POST, "/api/auth/register", "/api/auth/login").permitAll()
                        .requestMatchers("/internal/ai/v1/order-preparation", "/internal/ai/v1/order-drafts")
                        .hasRole("AGENT_ORDER_PREPARE")
                        .requestMatchers("/internal/ai/v1/**").hasRole("AGENT_READ")
                        .requestMatchers("/api/medicines/*/stock", "/message", "/stream").denyAll()
                        .requestMatchers("/api/**").hasRole("USER")
                        .requestMatchers("/", "/index.html", "/assets/**", "/favicon.ico").permitAll()
                        .anyRequest().denyAll())
                .exceptionHandling(e -> e
                        .authenticationEntryPoint((req, res, ex) -> error(res, 401,
                                "UNAUTHORIZED", "请登录或重新获取有效凭证"))
                        .accessDeniedHandler((req, res, ex) -> error(res, 403,
                                "FORBIDDEN", "没有访问权限")))
                .addFilterBefore(new BearerFilter(sessions, serviceKey),
                        UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    private static void error(jakarta.servlet.http.HttpServletResponse response, int status,
                              String code, String message) throws java.io.IOException {
        response.setStatus(status);
        response.setHeader("Cache-Control", "no-store");
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write("{\"code\":\"" + code + "\",\"message\":\"" + message + "\"}");
    }
}
