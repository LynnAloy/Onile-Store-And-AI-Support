package com.example.mybatisplus.controller;

import com.example.mybatisplus.dto.Requests;
import com.example.mybatisplus.security.CurrentUser;
import com.example.mybatisplus.service.UserService;
import com.example.mybatisplus.service.WalletService;
import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/wallet")
public class WalletController {
    private final WalletService wallet;
    private final UserService users;
    private final CurrentUser current;

    public WalletController(WalletService wallet, UserService users, CurrentUser current) {
        this.wallet = wallet;
        this.users = users;
        this.current = current;
    }

    @GetMapping("/{userId}")
    public Map<String, Object> get(@PathVariable String userId) {
        return users.getWalletData(current.username(userId));
    }

    @PostMapping("/recharge")
    public Map<String, Object> recharge(@Valid @RequestBody Requests.Recharge request) {
        return wallet.recharge(current.username(request.userId()), request.cardId());
    }

    @PostMapping("/exchange")
    public Map<String, Object> exchange(@Valid @RequestBody Requests.Exchange request) {
        return wallet.exchangePoints(current.username(request.userId()), request.points());
    }
}
