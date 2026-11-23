package com.example.mybatisplus.security;

import com.example.mybatisplus.exception.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;

@Component
public class CurrentUser {
    public Actor actor() {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !(authentication.getPrincipal() instanceof Actor actor)) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "UNAUTHORIZED", "请先登录");
        }
        return actor;
    }

    public String username(String supplied) {
        Actor actor = actor();
        if (supplied != null && !supplied.equals(actor.username())) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "无权访问其他用户的数据");
        }
        return actor.username();
    }
}
