package com.example.mybatisplus.mapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.mybatisplus.entity.Transaction;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;


@Mapper
public interface TransactionMapper extends BaseMapper<Transaction> {
}
