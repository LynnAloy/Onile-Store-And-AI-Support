package com.example.mybatisplus.service;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import org.springframework.transaction.annotation.Transactional;
import com.example.mybatisplus.entity.Medicine;
import com.example.mybatisplus.exception.ApiException;
import com.example.mybatisplus.mapper.MedicineMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;

// MedicineService.java
@Service
@Transactional(rollbackFor = Exception.class)
public class MedicineService {
    @Autowired
    private MedicineMapper medicineMapper;

    public List<Medicine> getMedicines(String name) {
        QueryWrapper<Medicine> queryWrapper = new QueryWrapper<>();

        // 按名称模糊查询
        if (StringUtils.hasText(name)) {
            queryWrapper.like("name", name);
        }
        return medicineMapper.selectList(queryWrapper);
    }

    @Transactional
    public void updateStock(Integer medicineId, Integer quantityChange) {
        Medicine medicine = medicineMapper.selectById(medicineId);
        if (medicine == null) {
            throw new ApiException("药品不存在");
        }

        int newStock = medicine.getStock() + quantityChange;
        if (newStock < 0) {
            throw new ApiException("库存不足");
        }

        medicine.setStock(newStock);
        medicineMapper.updateById(medicine);
    }
    //没有setStock() getStock() 方法
}