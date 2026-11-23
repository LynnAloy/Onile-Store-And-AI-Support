CREATE DATABASE  IF NOT EXISTS `deepseekdoc` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;
USE `deepseekdoc`;
-- MySQL dump 10.13  Distrib 8.0.42, for Win64 (x86_64)
--
-- Host: 127.0.0.1    Database: deepseekdoc
-- ------------------------------------------------------
-- Server version	8.0.40

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `medicines`
--

DROP TABLE IF EXISTS `medicines`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `medicines` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL,
  `price` decimal(10,2) NOT NULL,
  `stock` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `medicines`
--

LOCK TABLES `medicines` WRITE;
/*!40000 ALTER TABLE `medicines` DISABLE KEYS */;
INSERT INTO `medicines` VALUES (1,'布洛芬',10.80,50),(2,'板蓝根颗粒',7.90,95),(3,'枇杷露',19.90,8);
/*!40000 ALTER TABLE `medicines` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `order_items`
--

DROP TABLE IF EXISTS `order_items`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
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
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `order_items`
--

LOCK TABLES `order_items` WRITE;
/*!40000 ALTER TABLE `order_items` DISABLE KEYS */;
INSERT INTO `order_items` VALUES (1,'ORD_1751905888523',1,2,10.80),(2,'ORD_1751954791564',1,3,10.80),(3,'ORD_1751954791564',2,1,7.90),(4,'ORD_1751955514959',3,1,19.90),(5,'ORD_1751955640232',2,1,7.90),(6,'ORD_1751955843468',2,1,7.90),(7,'ORD_1751956512424',2,1,7.90),(8,'ORD_1751956512424',3,1,19.90);
/*!40000 ALTER TABLE `order_items` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `orders`
--

DROP TABLE IF EXISTS `orders`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
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
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `orders`
--

LOCK TABLES `orders` WRITE;
/*!40000 ALTER TABLE `orders` DISABLE KEYS */;
INSERT INTO `orders` VALUES ('ORD_1751905888523','48e3835eba3e531c0a78dfd224659518',21.60,'completed','2025-07-08 00:31:28','aloy','天津','15900896358',NULL),('ORD_1751954791564','48e3835eba3e531c0a78dfd224659518',40.30,'completed','2025-07-08 14:06:31',NULL,NULL,NULL,NULL),('ORD_1751955514959','48e3835eba3e531c0a78dfd224659518',19.90,'completed','2025-07-08 14:18:34',NULL,NULL,NULL,NULL),('ORD_1751955640232','48e3835eba3e531c0a78dfd224659518',7.90,'completed','2025-07-08 14:20:40',NULL,NULL,NULL,NULL),('ORD_1751955843468','48e3835eba3e531c0a78dfd224659518',7.90,'completed','2025-07-08 14:24:03',NULL,NULL,NULL,NULL),('ORD_1751956512424','48e3835eba3e531c0a78dfd224659518',27.80,'completed','2025-07-08 14:35:12','小草神','提瓦特','15900896345','快一点 可莉生病了');
/*!40000 ALTER TABLE `orders` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `recharge_cards`
--

DROP TABLE IF EXISTS `recharge_cards`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
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
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `recharge_cards`
--

LOCK TABLES `recharge_cards` WRITE;
/*!40000 ALTER TABLE `recharge_cards` DISABLE KEYS */;
INSERT INTO `recharge_cards` VALUES ('CARDX-05001',50.00,0,NULL,NULL),('CARDX-10001',100.00,1,'48e3835eba3e531c0a78dfd224659518','2025-07-07 22:41:03'),('CARDX-20001',200.00,0,NULL,NULL);
/*!40000 ALTER TABLE `recharge_cards` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `transactions`
--

DROP TABLE IF EXISTS `transactions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
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
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `transactions`
--

LOCK TABLES `transactions` WRITE;
/*!40000 ALTER TABLE `transactions` DISABLE KEYS */;
INSERT INTO `transactions` VALUES ('TX_1751899262719','48e3835eba3e531c0a78dfd224659518','recharge',100.00,NULL,'2025-07-07 22:41:02','CARDX-10001'),('TX_1751899588212','48e3835eba3e531c0a78dfd224659518','exchange',5.00,-50,'2025-07-07 22:46:28',NULL),('TX_1751905888558','48e3835eba3e531c0a78dfd224659518','purchase',-21.60,21,'2025-07-08 00:31:28','ORD_1751905888523'),('TX_1751954791590','48e3835eba3e531c0a78dfd224659518','purchase',-40.30,40,'2025-07-08 14:06:31','ORD_1751954791564'),('TX_1751955514980','48e3835eba3e531c0a78dfd224659518','purchase',-19.90,19,'2025-07-08 14:18:34','ORD_1751955514959'),('TX_1751955640234','48e3835eba3e531c0a78dfd224659518','purchase',-7.90,7,'2025-07-08 14:20:40','ORD_1751955640232'),('TX_1751955843476','48e3835eba3e531c0a78dfd224659518','purchase',-7.90,7,'2025-07-08 14:24:03','ORD_1751955843468'),('TX_1751956512438','48e3835eba3e531c0a78dfd224659518','purchase',-27.80,27,'2025-07-08 14:35:12','ORD_1751956512424');
/*!40000 ALTER TABLE `transactions` ENABLE KEYS */;
UNLOCK TABLES;


--
-- Table structure for table `message`
--

DROP TABLE IF EXISTS `message`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
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
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `message`
--

LOCK TABLES `message` WRITE;
/*!40000 ALTER TABLE `message` DISABLE KEYS */;
/*!40000 ALTER TABLE `message` ENABLE KEYS */;
UNLOCK TABLES;










--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
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
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES ('47b75041c99d85eb1e19b58e246bf9ce','hans','123456','extra',NULL,'apex',40,'Male','2025-07-01T16:00:00.000Z','15900899358','biejing','[\"选项1\", \"选项2\", \"选项3\"]',0.00,0,0,NULL,'mock_token_47b75041c99d85eb1e19b58e246bf9ce_1751946215797',NULL),('48e3835eba3e531c0a78dfd224659518','lynn','445556666','aloy','123@163.com',NULL,NULL,NULL,NULL,NULL,NULL,'[\"高血压\", \"脂肪肝\"]',72.20,171,1,'222222','mock_token_48e3835eba3e531c0a78dfd224659518_1751954665397','health_token_1751954784720'),('9cdb9754be8673d6c7b19128c0e50244','xxxx','123456',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0.00,0,0,NULL,NULL,NULL),('d6028c8fa90a868ff6ebbf6d47f91cb2','aloy','123456',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0.00,0,0,NULL,'mock_token_d6028c8fa90a868ff6ebbf6d47f91cb2_1751941919295',NULL);
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2025-07-08 14:42:58
