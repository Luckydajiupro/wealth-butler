-- ============================================================
-- 客户-理财顾问关联分配（根据实际员工ID）
-- ============================================================

USE wealth_butler;

-- 在 fin_customer_profile 表中添加 advisor_id 字段（如果不存在）
SET @exist := (SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='fin_customer_profile' AND COLUMN_NAME='advisor_id');
SET @sqlstmt := IF(@exist = 0,
    'ALTER TABLE `fin_customer_profile` ADD COLUMN `advisor_id` INT COMMENT ''负责理财顾问ID'' AFTER `customer_id`, ADD INDEX `idx_advisor_id` (`advisor_id`)',
    'SELECT ''advisor_id already exists'' AS message');
PREPARE stmt FROM @sqlstmt;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 更新客户画像表，分配理财顾问
-- 实际理财顾问：155, 160, 167 (初级)  156, 157 (高级)
-- 服务规范：
--   普通客户 -> 初级顾问 (155, 160, 167)
--   金卡客户 -> 初级或高级顾问 (155, 160, 167, 156, 157)
--   白金/钻石/私行客户 -> 高级顾问 (156, 157)

-- 普通客户 (1-90) 分配给初级顾问
UPDATE fin_customer_profile SET advisor_id = 155 WHERE customer_id BETWEEN 1 AND 30;
UPDATE fin_customer_profile SET advisor_id = 160 WHERE customer_id BETWEEN 31 AND 60;
UPDATE fin_customer_profile SET advisor_id = 167 WHERE customer_id BETWEEN 61 AND 90;

-- 金卡客户 (91-128) 分配给初级或高级顾问
UPDATE fin_customer_profile SET advisor_id = 155 WHERE customer_id BETWEEN 91 AND 100;
UPDATE fin_customer_profile SET advisor_id = 160 WHERE customer_id BETWEEN 101 AND 110;
UPDATE fin_customer_profile SET advisor_id = 167 WHERE customer_id BETWEEN 111 AND 118;
UPDATE fin_customer_profile SET advisor_id = 156 WHERE customer_id BETWEEN 119 AND 123;
UPDATE fin_customer_profile SET advisor_id = 157 WHERE customer_id BETWEEN 124 AND 128;

-- 白金客户 (129-143) 分配给高级顾问
UPDATE fin_customer_profile SET advisor_id = 156 WHERE customer_id BETWEEN 129 AND 136;
UPDATE fin_customer_profile SET advisor_id = 157 WHERE customer_id BETWEEN 137 AND 143;

-- 钻石客户 (144-149) 分配给高级顾问
UPDATE fin_customer_profile SET advisor_id = 156 WHERE customer_id BETWEEN 144 AND 146;
UPDATE fin_customer_profile SET advisor_id = 157 WHERE customer_id BETWEEN 147 AND 149;

-- 私行客户 (150) 分配给高级顾问
UPDATE fin_customer_profile SET advisor_id = 156 WHERE customer_id = 150;

-- 完成
