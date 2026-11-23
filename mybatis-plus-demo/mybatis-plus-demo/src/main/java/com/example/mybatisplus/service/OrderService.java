package com.example.mybatisplus.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.example.mybatisplus.dto.OrderDTO;
import com.example.mybatisplus.dto.OrderItemDTO;
import com.example.mybatisplus.entity.*;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.mapper.*;
import com.example.mybatisplus.security.SessionService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderService {
    private final OrderMapper orders;
    private final OrderItemMapper items;
    private final MedicineMapper medicines;
    private final UserMapper users;
    private final TransactionMapper ledger;
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;

    public OrderService(OrderMapper orders, OrderItemMapper items, MedicineMapper medicines,
                        UserMapper users, TransactionMapper ledger, JdbcTemplate jdbc, ObjectMapper json) {
        this.orders = orders;
        this.items = items;
        this.medicines = medicines;
        this.users = users;
        this.ledger = ledger;
        this.jdbc = jdbc;
        this.json = json;
    }

    public static String newId(String prefix) {
        return prefix + UUID.randomUUID().toString().replace("-", "").substring(0, 24);
    }

    @Transactional
    public Map<String, Object> submitOrder(String username, OrderDTO request, String requestKey) {
        User user = users.selectOne(new QueryWrapper<User>().eq("user_id", username).last("FOR UPDATE"));
        String fingerprint = fingerprint(request);
        var previous = jdbc.queryForList(
                "SELECT order_id,request_hash FROM checkout_requests WHERE user_id=? AND request_key=?",
                user.getId(), requestKey);
        if (!previous.isEmpty()) {
            if (!fingerprint.equals(previous.getFirst().get("request_hash"))) {
                throw new ApiException(HttpStatus.CONFLICT, "IDEMPOTENCY_CONFLICT", "相同请求键不能用于不同订单");
            }
            Order order = orders.selectById((String) previous.getFirst().get("order_id"));
            return result(order, user);
        }
        // Lock products in a stable order; duplicate product lines are rejected.
        SortedMap<Integer, Integer> quantities = new TreeMap<>();
        for (OrderItemDTO item : request.getItems()) {
            if (quantities.put(item.getMedicineId(), item.getQuantity()) != null) {
                throw new ApiException("同一药品不能重复提交");
            }
        }
        BigDecimal total = BigDecimal.ZERO;
        List<OrderItem> lines = new ArrayList<>();
        for (var entry : quantities.entrySet()) {
            Medicine medicine = medicines.selectOne(
                    new QueryWrapper<Medicine>().eq("id", entry.getKey()).last("FOR UPDATE"));
            if (medicine == null) throw new ApiException("药品不存在");
            SalePolicy.require(medicine);
            if (medicine.getStock() < entry.getValue()) throw new ApiException("药品库存不足");
            if (medicine.getPrice() == null || medicine.getPrice().signum() <= 0) {
                throw new ApiException("药品价格无效");
            }
            OrderItem line = new OrderItem();
            line.setMedicineId(medicine.getId());
            line.setQuantity(entry.getValue());
            line.setPrice(medicine.getPrice());
            lines.add(line);
            total = total.add(medicine.getPrice().multiply(BigDecimal.valueOf(entry.getValue())));
        }
        if (user.getBalance().compareTo(total) < 0) throw new ApiException("余额不足");
        Order order = new Order();
        order.setId(newId("ORD_"));
        order.setUserId(user.getId());
        order.setTotalPrice(total);
        order.setStatus("completed");
        order.setCreatedAt(new Date());
        order.setRecipientName(request.getRecipientName());
        order.setRecipientAddress(request.getRecipientAddress());
        order.setRecipientPhone(request.getRecipientPhone());
        order.setNote(request.getNote());
        orders.insert(order);
        for (OrderItem line : lines) {
            int changed = medicines.update(null, new UpdateWrapper<Medicine>()
                    .eq("id", line.getMedicineId()).ge("stock", line.getQuantity())
                    .setSql("stock = stock - " + line.getQuantity()));
            if (changed != 1) throw new ApiException("库存变化，请重新确认");
            line.setOrderId(order.getId());
            items.insert(line);
        }
        user.setBalance(user.getBalance().subtract(total));
        user.setPoints(Math.addExact(user.getPoints(), total.intValue()));
        // Keep fractional currency in BigDecimal; earned points use the integer yuan amount.
        users.update(null, new UpdateWrapper<User>().eq("id", user.getId())
                .set("balance", user.getBalance()).set("points", user.getPoints()));
        Transaction tx = new Transaction();
        tx.setId(newId("TX_"));
        tx.setUserId(user.getId());
        tx.setType("purchase");
        tx.setAmount(total.negate());
        tx.setPointsChange(total.intValue());
        tx.setCreatedAt(new Date());
        tx.setRelatedId(order.getId());
        ledger.insert(tx);
        jdbc.update("INSERT INTO checkout_requests(user_id,request_key,request_hash,order_id) VALUES (?,?,?,?)",
                user.getId(), requestKey, fingerprint, order.getId());
        return result(order, user);
    }

    private String fingerprint(OrderDTO request) {
        try {
            var normalized = new TreeMap<Integer, Integer>();
            for (OrderItemDTO item : request.getItems()) {
                if (normalized.put(item.getMedicineId(), item.getQuantity()) != null) {
                    throw new ApiException("同一药品不能重复提交");
                }
            }
            return SessionService.digest(json.writeValueAsString(Arrays.asList(
                    request.getRecipientName(), request.getRecipientAddress(),
                    request.getRecipientPhone(), request.getNote(), normalized)));
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException(ex);
        }
    }

    private Map<String, Object> result(Order order, User user) {
        return Map.of("orderId", order.getId(), "points", order.getTotalPrice().intValue(),
                "newBalance", user.getBalance(), "totalPoints", user.getPoints());
    }

    public List<Order> searchOrders(String username, String phone) {
        User user = users.selectOne(new QueryWrapper<User>().eq("user_id", username));
        var query = new QueryWrapper<Order>().eq("user_id", user.getId()).orderByDesc("created_at");
        if (phone != null && !phone.isBlank()) query.eq("recipient_phone", phone);
        List<Order> result = orders.selectList(query);
        result.forEach(this::loadItems);
        return result;
    }

    public Order getOrder(String username, String orderId) {
        User user = users.selectOne(new QueryWrapper<User>().eq("user_id", username));
        Order order = orders.selectOne(
                new QueryWrapper<Order>().eq("id", orderId).eq("user_id", user.getId()));
        if (order == null) {
            throw new ApiException(HttpStatus.NOT_FOUND, "ORDER_NOT_FOUND", "订单不存在");
        }
        loadItems(order);
        return order;
    }

    private void loadItems(Order order) {
        List<OrderItem> lines = items.selectList(new QueryWrapper<OrderItem>().eq("order_id", order.getId()));
        lines.forEach(line -> {
            Medicine medicine = medicines.selectById(line.getMedicineId());
            line.setName(medicine == null ? "商品已下架" : medicine.getName());
        });
        order.setItems(lines);
    }

    public void deleteOrder(String username, String orderId) {
        getOrder(username, orderId);
        // Preserve the financial audit trail. Cancellation/refund belongs to M5.
        throw new ApiException(HttpStatus.CONFLICT, "ORDER_DELETE_DISABLED", "交易订单不可删除");
    }
}
