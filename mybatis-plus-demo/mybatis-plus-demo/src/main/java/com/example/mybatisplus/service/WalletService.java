package com.example.mybatisplus.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.example.mybatisplus.entity.*;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.mapper.*;
import java.math.BigDecimal;
import java.util.Date;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class WalletService {
    private final UserMapper users;
    private final RechargeCardMapper cards;
    private final TransactionMapper ledger;

    public WalletService(UserMapper users, RechargeCardMapper cards, TransactionMapper ledger) {
        this.users = users;
        this.cards = cards;
        this.ledger = ledger;
    }

    private User lockUser(String username) {
        User user = users.selectOne(new QueryWrapper<User>().eq("user_id", username).last("FOR UPDATE"));
        if (user == null || !Boolean.TRUE.equals(user.getWalletActivated())) {
            throw new ApiException("请先激活钱包");
        }
        return user;
    }

    @Transactional
    public Map<String, Object> recharge(String username, String cardId) {
        User user = lockUser(username);
        RechargeCard card = cards.selectOne(new QueryWrapper<RechargeCard>().eq("id", cardId).last("FOR UPDATE"));
        if (card == null || Boolean.TRUE.equals(card.getIsUsed()) || card.getAmount().signum() <= 0) {
            throw new ApiException("无效或已使用的充值卡");
        }
        user.setBalance(user.getBalance().add(card.getAmount()));
        users.update(null, new UpdateWrapper<User>().eq("id", user.getId()).set("balance", user.getBalance()));
        card.setIsUsed(true);
        card.setUsedBy(user.getId());
        card.setUsedAt(new Date());
        cards.updateById(card);
        record(user, "recharge", card.getAmount(), 0, cardId);
        return Map.of("newBalance", user.getBalance(), "amount", card.getAmount());
    }

    @Transactional
    public Map<String, Object> exchangePoints(String username, Integer points) {
        if (points == null || points <= 0) throw new ApiException("兑换积分必须大于0");
        User user = lockUser(username);
        if (points > user.getPoints()) throw new ApiException("积分不足");
        BigDecimal amount = BigDecimal.valueOf(points).divide(BigDecimal.TEN);
        user.setPoints(user.getPoints() - points);
        user.setBalance(user.getBalance().add(amount));
        users.update(null, new UpdateWrapper<User>().eq("id", user.getId())
                .set("balance", user.getBalance()).set("points", user.getPoints()));
        record(user, "exchange", amount, -points, null);
        return Map.of("newBalance", user.getBalance(), "newPoints", user.getPoints());
    }

    private void record(User user, String type, BigDecimal amount, int points, String related) {
        Transaction tx = new Transaction();
        tx.setId(OrderService.newId("TX_"));
        tx.setUserId(user.getId());
        tx.setType(type);
        tx.setAmount(amount);
        tx.setPointsChange(points);
        tx.setCreatedAt(new Date());
        tx.setRelatedId(related);
        ledger.insert(tx);
    }
}
