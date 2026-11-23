package com.example.mybatisplus.controller;

import com.example.mybatisplus.entity.Transaction;
import com.example.mybatisplus.security.CurrentUser;
import com.example.mybatisplus.service.TransactionService;
import java.util.List;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/transactions")
public class TransactionController {
    private final TransactionService transactions;
    private final CurrentUser current;

    public TransactionController(TransactionService transactions, CurrentUser current) {
        this.transactions = transactions;
        this.current = current;
    }

    @GetMapping
    public List<Transaction> list(@RequestParam(required = false) String userId) {
        return transactions.getByLoginName(current.username(userId));
    }
}
