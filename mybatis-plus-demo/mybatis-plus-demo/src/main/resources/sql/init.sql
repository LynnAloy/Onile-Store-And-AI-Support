-- MyBatis-Plus Demo 数据库初始化脚本
-- 创建数据库

-- 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS `mybatis_plus_demo` 
DEFAULT CHARACTER SET utf8mb4 
DEFAULT COLLATE utf8mb4_unicode_ci;

-- 数据库创建完成
SELECT '数据库创建完成！' AS '状态';
SELECT '请执行 user_table.sql 创建表并插入测试数据' AS '提示';