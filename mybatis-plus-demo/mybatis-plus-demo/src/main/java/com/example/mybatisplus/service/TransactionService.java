package com.example.mybatisplus.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.example.mybatisplus.entity.Transaction;
import com.example.mybatisplus.entity.User;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.mapper.TransactionMapper;
import com.example.mybatisplus.mapper.UserMapper;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class TransactionService {
    private final TransactionMapper transactionMapper;
    private final UserMapper userMapper;

    public TransactionService(TransactionMapper transactionMapper,
                              UserMapper userMapper) {
        this.transactionMapper = transactionMapper;
        this.userMapper = userMapper;
    }

    public List<Transaction> getByLoginName(String loginName) {
        // 先查用户主键
        User user = userMapper.selectOne(
                new QueryWrapper<User>().eq("user_id", loginName)
        );
        if (user == null) {
            throw new ApiException("用户不存在：" + loginName);
        }
        // 用主键去 transactions 表里查
        return transactionMapper.selectList(
                new QueryWrapper<Transaction>().eq("user_id", user.getId())
        );
    }
}

