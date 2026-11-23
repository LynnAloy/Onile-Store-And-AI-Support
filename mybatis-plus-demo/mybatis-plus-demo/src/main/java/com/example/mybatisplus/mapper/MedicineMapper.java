package com.example.mybatisplus.mapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.mybatisplus.entity.Medicine;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface MedicineMapper extends BaseMapper<Medicine> {
}
