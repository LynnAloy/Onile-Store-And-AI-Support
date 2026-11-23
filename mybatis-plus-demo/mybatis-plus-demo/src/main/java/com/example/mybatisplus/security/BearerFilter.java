package com.example.mybatisplus.security;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

public class BearerFilter extends OncePerRequestFilter {
    private final SessionService sessions;
    private final String serviceKey;

    public BearerFilter(SessionService sessions, String serviceKey) {
        this.sessions = sessions;
        this.serviceKey = serviceKey;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String path = org.springframework.web.util.UrlPathHelper.defaultInstance.getPathWithinApplication(request);
        String header = request.getHeader("Authorization");
        if (header != null && header.startsWith("Bearer ")) {
            Actor actor = sessions.resolve(header.substring(7));
            boolean internal = path.startsWith("/internal/");
            String suppliedKey = request.getHeader("X-AI-Service-Key");
            boolean service = serviceKey.length() >= 32 && suppliedKey != null
                    && MessageDigest.isEqual(serviceKey.getBytes(StandardCharsets.UTF_8),
                            suppliedKey.getBytes(StandardCharsets.UTF_8));
            if (actor != null && (!internal || service)) {
                var authority = new SimpleGrantedAuthority("ROLE_" + actor.scope());
                var auth = new UsernamePasswordAuthenticationToken(actor, null, List.of(authority));
                SecurityContextHolder.getContext().setAuthentication(auth);
            }
        }
        chain.doFilter(request, response);
    }
}
