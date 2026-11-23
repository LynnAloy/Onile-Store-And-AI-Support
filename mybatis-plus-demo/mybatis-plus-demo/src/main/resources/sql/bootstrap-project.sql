-- New empty project database only. No DROP, USE, credentials or personal records.
-- Legacy credential column sizes are upgraded by V001 after the pre-migration backup.
CREATE TABLE `users` (
  `id` varchar(36) NOT NULL COMMENT '用户ID',
  `user_id` varchar(50) NOT NULL COMMENT '用户名',
  `password` varchar(100) NOT NULL COMMENT '密码',
  `nickname` varchar(50) DEFAULT NULL COMMENT '昵称',
  `email` varchar(100) DEFAULT NULL COMMENT '邮箱',
  `name` varchar(50) DEFAULT NULL COMMENT '真实姓名',
  `age` int DEFAULT NULL COMMENT '年龄',
  `gender` enum('Male','Female') DEFAULT NULL COMMENT '性别',
  `birthday` varchar(30) DEFAULT NULL,
  `phone_num` varchar(20) DEFAULT NULL COMMENT '手机号',
  `address` varchar(255) DEFAULT NULL COMMENT '地址',
  `medical_history` json DEFAULT NULL COMMENT '既往病史',
  `balance` decimal(10,2) DEFAULT '0.00' COMMENT '钱包余额',
  `points` int DEFAULT '0' COMMENT '健康积分',
  `wallet_activated` tinyint(1) DEFAULT '0' COMMENT '钱包是否激活',
  `walletPassword` varchar(40) DEFAULT NULL,
  `token` varchar(255) DEFAULT NULL COMMENT '登录Token',
  `health_token` varchar(255) DEFAULT NULL COMMENT '健康钱包Token',
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `medicines` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL,
  `price` decimal(10,2) NOT NULL,
  `stock` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `orders` (
  `id` varchar(30) NOT NULL COMMENT '订单ID',
  `user_id` varchar(36) NOT NULL COMMENT '用户ID',
  `total_price` decimal(10,2) NOT NULL COMMENT '总金额',
  `status` enum('pending','completed','cancelled') DEFAULT 'pending',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `recipient_name` varchar(15) DEFAULT NULL,
  `recipient_address` varchar(50) DEFAULT NULL,
  `recipient_phone` varchar(20) DEFAULT NULL,
  `note` varchar(200) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `orders_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `order_items` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_id` varchar(30) NOT NULL,
  `medicine_id` int NOT NULL,
  `quantity` int NOT NULL,
  `price` decimal(10,2) NOT NULL COMMENT '购买时单价',
  PRIMARY KEY (`id`),
  KEY `order_id` (`order_id`),
  KEY `medicine_id` (`medicine_id`),
  CONSTRAINT `order_items_ibfk_1` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`),
  CONSTRAINT `order_items_ibfk_2` FOREIGN KEY (`medicine_id`) REFERENCES `medicines` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `recharge_cards` (
  `id` varchar(20) NOT NULL,
  `amount` decimal(10,2) NOT NULL,
  `is_used` tinyint(1) DEFAULT '0',
  `used_by` varchar(36) DEFAULT NULL COMMENT '使用者ID',
  `used_at` datetime DEFAULT NULL COMMENT '使用时间',
  PRIMARY KEY (`id`),
  KEY `used_by` (`used_by`),
  CONSTRAINT `recharge_cards_ibfk_1` FOREIGN KEY (`used_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `transactions` (
  `id` varchar(30) NOT NULL COMMENT '交易ID',
  `user_id` varchar(36) NOT NULL,
  `type` enum('recharge','purchase','exchange') NOT NULL,
  `amount` decimal(10,2) DEFAULT NULL COMMENT '金额变动',
  `points_change` int DEFAULT NULL COMMENT '积分变动',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `related_id` varchar(50) DEFAULT NULL COMMENT '关联ID(订单ID/卡号)',
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `transactions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `message` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '消息ID，自增主键',
  `sender` varchar(50) NOT NULL COMMENT '发送者标识',
  `content` text NOT NULL COMMENT '消息内容',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（自动记录）',
  `user_id` varchar(36) DEFAULT NULL COMMENT '关联用户ID',
  PRIMARY KEY (`id`),
  KEY `idx_sender` (`sender`),
  KEY `idx_created_at` (`created_at`),
  KEY `idx_user_id` (`user_id`),
  CONSTRAINT `fk_message_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='系统消息表';

-- Original training catalog; demonstration data, not reviewed clinical recommendations.
INSERT INTO `medicines` VALUES (1,'布洛芬',10.80,50),(2,'板蓝根颗粒',7.90,95),(3,'枇杷露',19.90,8);
