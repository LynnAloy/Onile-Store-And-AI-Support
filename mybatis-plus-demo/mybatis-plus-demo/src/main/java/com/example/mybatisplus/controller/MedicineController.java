package com.example.mybatisplus.controller;

import com.example.mybatisplus.entity.Medicine;
import com.example.mybatisplus.service.MedicineService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/medicines")
public class MedicineController {

    @Autowired
    private MedicineService medicineService;

    @GetMapping
    public List<Medicine> getMedicines(@RequestParam(required = false) String name) {
        return medicineService.getMedicines(name);
    }

    @PutMapping("/{id}/stock")
    public void updateStock(
            @PathVariable Integer id,
            @RequestParam Integer quantity
    ) {
        medicineService.updateStock(id, quantity);
    }
}