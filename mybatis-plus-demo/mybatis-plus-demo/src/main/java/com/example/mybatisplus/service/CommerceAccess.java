package com.example.mybatisplus.service;

import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.security.Actor;
import com.example.mybatisplus.security.SessionService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class CommerceAccess {
    private final JdbcTemplate db;
    private final SessionService sessions;
    private final boolean enabled;
    public CommerceAccess(JdbcTemplate db, SessionService sessions,
            @Value("${commerce.enabled:false}") boolean enabled) {
        this.db=db; this.sessions=sessions; this.enabled=enabled;
    }
    public void available() {
        if (!enabled) throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE,"COMMERCE_DISABLED","管理与智能下单功能尚未启用");
    }
    public void identity(Actor actor, String raw) {
        available();
        Actor fresh=sessions.resolve(raw);
        if (fresh==null || !fresh.equals(actor)) throw new ApiException(HttpStatus.UNAUTHORIZED,"UNAUTHORIZED","登录已失效");
        if (!"USER".equals(fresh.scope())) throw new ApiException(HttpStatus.FORBIDDEN,"FORBIDDEN","需要本人登录凭证");
    }
    public boolean admin(Actor actor) {
        return enabled && "USER".equals(actor.scope()) && db.queryForObject(
                "SELECT COUNT(*) FROM account_roles WHERE user_id=? AND role='ADMIN'",Integer.class,actor.id())==1;
    }
    public void requireAdmin(Actor actor, String raw) {
        identity(actor,raw);
        if (!admin(actor)) throw new ApiException(HttpStatus.FORBIDDEN,"FORBIDDEN","仅管理员可执行此操作");
    }
}
