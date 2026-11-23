-- 家庭成员表创建和测试数据脚本
-- 负责创建家庭成员表并插入测试数据

-- 使用数据库
USE `mybatis_plus_demo`;

-- 删除已存在的表
DROP TABLE IF EXISTS `family_member`;

-- 创建家庭成员表
CREATE TABLE `family_member` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `name` VARCHAR(50) NOT NULL COMMENT '姓名',
    `role` VARCHAR(20) NULL DEFAULT NULL COMMENT '家庭成员角色（爸爸、妈妈、爷爷、奶奶、老爷、姥姥、大儿子、二女儿等）',
    `phone` VARCHAR(20) NULL DEFAULT NULL COMMENT '联系电话',
    `birthday` DATE NULL DEFAULT NULL COMMENT '生日',
    `blood_type` VARCHAR(5) NULL DEFAULT NULL COMMENT '血型（A、B、AB、O）',
    `create_time` DATETIME NULL DEFAULT NULL COMMENT '创建时间',
    `update_time` DATETIME NULL DEFAULT NULL COMMENT '更新时间',
    `version` INT NULL DEFAULT 1 COMMENT '版本号（乐观锁）',
    `deleted` INT NULL DEFAULT 0 COMMENT '逻辑删除标志（0-未删除，1-已删除）',
    PRIMARY KEY (`id`),
    INDEX `idx_name` (`name`),
    INDEX `idx_role` (`role`),
    INDEX `idx_blood_type` (`blood_type`),
    INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='家庭成员表';

-- 插入测试数据
INSERT INTO `family_member` (`id`, `name`, `role`, `phone`, `birthday`, `blood_type`, `create_time`, `update_time`, `version`, `deleted`) VALUES
(1, '张建国', '爸爸', '13800138001', '1968-03-15', 'A', NOW(), NOW(), 1, 0),
(2, '李美华', '妈妈', '13800138002', '1971-07-22', 'B', NOW(), NOW(), 1, 0),
(3, '张小明', '大儿子', '13800138003', '1995-11-08', 'O', NOW(), NOW(), 1, 0),
(4, '张小丽', '二女儿', '13800138004', '1998-05-12', 'AB', NOW(), NOW(), 1, 0),
(5, '王小红', '大儿媳', '13800138005', '1997-09-18', 'A', NOW(), NOW(), 1, 0),
(6, '张小宝', '孙子', NULL, '2020-12-25', 'O', NOW(), NOW(), 1, 0),
(7, '张老爷子', '爷爷', '13800138007', '1945-01-10', 'B', NOW(), NOW(), 1, 0),
(8, '李奶奶', '奶奶', '13800138008', '1948-06-30', 'A', NOW(), NOW(), 1, 0),
(9, '张大伯', '大伯', '13800138009', '1965-04-20', 'AB', NOW(), NOW(), 1, 0),
(10, '陈大妈', '大伯母', '13800138010', '1967-08-14', 'B', NOW(), NOW(), 1, 0),
(11, '张小强', '堂哥', '13800138011', '1993-02-28', 'O', NOW(), NOW(), 1, 0),
(12, '李小芳', '堂嫂', '13800138012', '1994-10-05', 'A', NOW(), NOW(), 1, 0);

-- 重置自增ID
ALTER TABLE `family_member` AUTO_INCREMENT = 13;

-- 查询验证数据
SELECT COUNT(*) AS '家庭成员总数' FROM `family_member` WHERE `deleted` = 0;
SELECT * FROM `family_member` WHERE `deleted` = 0 ORDER BY `id` LIMIT 5;

SELECT '家庭成员表创建和测试数据插入完成！' AS '状态';