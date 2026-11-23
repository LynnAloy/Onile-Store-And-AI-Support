-- 用户表创建和测试数据脚本
-- 负责创建用户表并插入测试数据

-- 使用数据库
USE `mybatis_plus_demo`;

-- 删除已存在的表
DROP TABLE IF EXISTS `user`;

-- 创建用户表
CREATE TABLE `user` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `name` VARCHAR(30) NULL DEFAULT NULL COMMENT '姓名',
    `age` INT NULL DEFAULT NULL COMMENT '年龄',
    `email` VARCHAR(50) NULL DEFAULT NULL COMMENT '邮箱',
    `create_time` DATETIME NULL DEFAULT NULL COMMENT '创建时间',
    `update_time` DATETIME NULL DEFAULT NULL COMMENT '更新时间',
    `version` INT NULL DEFAULT 1 COMMENT '版本号（乐观锁）',
    `deleted` INT NULL DEFAULT 0 COMMENT '逻辑删除标志（0-未删除，1-已删除）',
    PRIMARY KEY (`id`),
    INDEX `idx_name` (`name`),
    INDEX `idx_age` (`age`),
    INDEX `idx_email` (`email`),
    INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- 插入测试数据
INSERT INTO `user` (`id`, `name`, `age`, `email`, `create_time`, `update_time`, `version`, `deleted`) VALUES
(1, 'Jone', 18, 'test1@baomidou.com', NOW(), NOW(), 1, 0),
(2, 'Jack', 20, 'test2@baomidou.com', NOW(), NOW(), 1, 0),
(3, 'Tom', 28, 'test3@baomidou.com', NOW(), NOW(), 1, 0),
(4, 'Sandy', 21, 'test4@baomidou.com', NOW(), NOW(), 1, 0),
(5, 'Billie', 24, 'test5@baomidou.com', NOW(), NOW(), 1, 0),
(6, 'Alice', 22, 'alice@example.com', NOW(), NOW(), 1, 0),
(7, 'Bob', 25, 'bob@example.com', NOW(), NOW(), 1, 0),
(8, 'Charlie', 30, 'charlie@gmail.com', NOW(), NOW(), 1, 0),
(9, 'Diana', 19, 'diana@gmail.com', NOW(), NOW(), 1, 0),
(10, 'Eve', 27, 'eve@yahoo.com', NOW(), NOW(), 1, 0),
(11, 'Frank', 35, 'frank@yahoo.com', NOW(), NOW(), 1, 0),
(12, 'Grace', 23, 'grace@hotmail.com', NOW(), NOW(), 1, 0),
(13, 'Henry', 29, 'henry@hotmail.com', NOW(), NOW(), 1, 0),
(14, 'Ivy', 26, 'ivy@outlook.com', NOW(), NOW(), 1, 0),
(15, 'Jack2', 31, 'jack2@outlook.com', NOW(), NOW(), 1, 0);

-- 重置自增ID
ALTER TABLE `user` AUTO_INCREMENT = 16;

-- 查询验证数据
SELECT COUNT(*) AS '总用户数' FROM `user` WHERE `deleted` = 0;
SELECT * FROM `user` WHERE `deleted` = 0 ORDER BY `id` LIMIT 5;

SELECT '用户表创建和测试数据插入完成！' AS '状态';