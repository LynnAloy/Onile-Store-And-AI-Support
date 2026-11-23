package com.example.mybatisplus.controller;

import com.example.mybatisplus.dto.Requests;
import com.example.mybatisplus.security.CurrentUser;
import com.example.mybatisplus.security.SessionService;
import com.example.mybatisplus.service.UserService;
import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private final UserService users;
    private final CurrentUser current;
    private final SessionService sessions;

    public AuthController(UserService users, CurrentUser current, SessionService sessions) {
        this.users = users;
        this.current = current;
        this.sessions = sessions;
    }

    @PostMapping("/register")
    public Map<String, Object> register(@Valid @RequestBody Requests.Credentials request) {
        return users.register(request.userId(), request.password());
    }

    @PostMapping("/login")
    public Map<String, Object> login(@Valid @RequestBody Requests.Login request) {
        return users.login(request.userId(), request.password());
    }

    @PostMapping("/logout")
    public void logout(@RequestBody(required = false) Requests.Logout request) {
        current.username(request == null ? null : request.userId());
        sessions.logout(current.actor());
    }

    @PostMapping("/activate-wallet")
    public Map<String, Object> activate(@Valid @RequestBody Requests.WalletSetup request) {
        return users.activateWallet(current.username(request.userId()), request.password());
    }

    @PostMapping("/agent-token")
    public Map<String, Object> delegate() {
        return sessions.delegate(current.actor());
    }
}
