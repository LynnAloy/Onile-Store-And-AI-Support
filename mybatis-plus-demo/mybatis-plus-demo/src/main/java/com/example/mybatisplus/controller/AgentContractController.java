package com.example.mybatisplus.controller;

import com.example.mybatisplus.entity.Medicine;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.mapper.MedicineMapper;
import com.example.mybatisplus.security.CurrentUser;
import com.example.mybatisplus.service.MedicineService;
import com.example.mybatisplus.service.OrderService;
import java.util.List;
import java.util.Map;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/ai/v1")
public class AgentContractController {
    private final CurrentUser current;
    private final com.example.mybatisplus.service.MedicineEvidenceService evidence;
    private final MedicineService medicines;
    private final MedicineMapper medicineMapper;
    private final OrderService orders;
    private final com.example.mybatisplus.service.PaymentService payments;
    private final com.example.mybatisplus.service.UserService users;

    public AgentContractController(CurrentUser current, MedicineService medicines,
                                   MedicineMapper medicineMapper, OrderService orders,
                                   com.example.mybatisplus.service.UserService users,
                                   com.example.mybatisplus.service.PaymentService payments,
                                   com.example.mybatisplus.service.MedicineEvidenceService evidence) {
        this.current = current;
        this.evidence = evidence;
        this.medicines = medicines;
        this.medicineMapper = medicineMapper;
        this.orders = orders;
        this.users = users;
        this.payments = payments;
    }

    @GetMapping("/me")
    public Map<String, String> me() {
        return Map.of("userId", current.actor().username(), "scope", current.actor().scope());
    }

    @GetMapping("/personalization-status")
    public org.springframework.http.ResponseEntity<?> personalizationStatus() {
        return org.springframework.http.ResponseEntity.ok().header("Cache-Control", "no-store")
                .body(users.personalizationStatus(current.username(null)));
    }

    @GetMapping("/personalization-context")
    public org.springframework.http.ResponseEntity<?> personalizationContext() {
        return org.springframework.http.ResponseEntity.ok().header("Cache-Control", "no-store")
                .body(users.personalizationContext(current.username(null)));
    }

    @GetMapping("/medicines")
    public List<Medicine> search(@RequestParam(required = false) String name,
                                 @RequestParam(defaultValue = "10") Integer limit) {
        if (name != null && name.length() > 100) throw new ApiException("关键词过长");
        if (limit < 1 || limit > 20) throw new ApiException("查询数量应为1至20");
        var query = new QueryWrapper<Medicine>().orderByAsc("id").last("LIMIT " + limit);
        if (name != null && !name.isBlank()) query.like("name", name.strip());
        return medicineMapper.selectList(query);
    }

    @GetMapping("/catalog")
    public List<Map<String,Object>> catalog(@RequestParam(defaultValue="0") int afterId) {
        if (afterId<0) throw new ApiException("目录游标不合法");
        return medicineMapper.selectList(new QueryWrapper<Medicine>().gt("id",afterId).orderByAsc("id").last("LIMIT 20")).stream().map(item -> {
            Map<String,Object> row=new java.util.LinkedHashMap<>();
            row.put("id",item.getId()); row.put("name",item.getName()); row.put("price",item.getPrice()); row.put("stock",item.getStock());
            row.put("draftEligible",item.isDraftEligible()); row.put("draftBlockedReason",item.getDraftBlockedReason());
            row.put("qualificationVersion",item.getQualificationVersion());
            row.put("medicalEvidence",evidence.read(item.getId(),item.getQualificationVersion()));
            return row;
        }).toList();
    }

    @GetMapping("/medicines/{id}")
    public Medicine detail(@PathVariable Integer id) {
        if (id < 1) throw new ApiException("商品ID必须为正数");
        Medicine medicine = medicineMapper.selectById(id);
        if (medicine == null) throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "药品不存在");
        return medicine;
    }

    @GetMapping("/orders/{orderId}")
    public Map<String, Object> order(@PathVariable String orderId) {
        if (!orderId.matches("[A-Za-z0-9_-]{1,64}")) throw new ApiException("订单号格式不正确");
        if (payments.enabled()) return payments.agentSummary(current.actor(),orderId);
        var order = orders.getOrder(current.username(null), orderId);
        // No recipient address, phone, login credentials, or payment data sent to the model.
        return Map.of("orderId", order.getId(), "status", order.getStatus(),
                "totalPrice", order.getTotalPrice(), "currency", "CNY",
                "items", order.getItems());
    }
}
