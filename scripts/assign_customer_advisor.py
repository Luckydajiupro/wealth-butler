"""
客户-员工关联分配脚本
根据客户等级匹配相应级别的理财顾问
"""
import random

# 客户服务规范：客户等级 -> 理财顾问等级
SERVICE_RULES = {
    '普通': ['初级', '中级'],      # 普通客户：初级或中级顾问
    '金卡': ['中级', '高级'],      # 金卡客户：中级或高级顾问
    '白金': ['高级'],              # 白金客户：高级顾问
    '钻石': ['高级'],              # 钻石客户：高级顾问
    '私行': ['高级']               # 私行客户：高级顾问
}

def generate_assignment_sql():
    """生成客户-员工关联SQL"""

    # 从数据库读取员工信息（理财顾问）
    advisors = {
        '初级': [203, 216],  # employee003, employee016
        '中级': [202, 204, 217],  # employee002, employee004, employee017
        '高级': [201, 205]  # employee001, employee005
    }

    # 客户等级分布
    customers = {
        '普通': list(range(1, 91)),      # 1-90: 普通客户
        '金卡': list(range(91, 129)),    # 91-128: 金卡客户
        '白金': list(range(129, 144)),   # 129-143: 白金客户
        '钻石': list(range(144, 150)),   # 144-149: 钻石客户
        '私行': [150]                     # 150: 私行客户
    }

    assignments = []

    for level, customer_ids in customers.items():
        allowed_levels = SERVICE_RULES[level]

        for customer_id in customer_ids:
            # 根据规则选择顾问等级
            advisor_level = random.choice(allowed_levels)
            # 从该等级的顾问中随机选择一个
            advisor_id = random.choice(advisors[advisor_level])

            assignments.append({
                'customer_id': customer_id,
                'advisor_id': advisor_id,
                'advisor_level': advisor_level,
                'customer_level': level
            })

    return assignments

def main():
    print("="*60)
    print("客户-员工关联分配")
    print("="*60)

    assignments = generate_assignment_sql()

    with open('scripts/customer_advisor_assignment.sql', 'w', encoding='utf-8') as f:
        f.write("-- ============================================================\n")
        f.write("-- 客户-理财顾问关联分配\n")
        f.write("-- 根据客户等级匹配相应级别的理财顾问\n")
        f.write("-- ============================================================\n\n")
        f.write("USE wealth_butler;\n\n")

        f.write("-- 在 fin_customer_profile 表中添加 advisor_id 字段（如果不存在）\n")
        f.write("ALTER TABLE `fin_customer_profile` \n")
        f.write("ADD COLUMN IF NOT EXISTS `advisor_id` INT COMMENT '负责理财顾问ID' AFTER `customer_id`,\n")
        f.write("ADD INDEX IF NOT EXISTS `idx_advisor_id` (`advisor_id`);\n\n")

        f.write("-- 更新客户画像表，分配理财顾问\n")
        for assign in assignments:
            f.write(f"UPDATE `fin_customer_profile` SET `advisor_id` = {assign['advisor_id']} "
                   f"WHERE `customer_id` = {assign['customer_id']};\n")

        f.write("\n-- 完成\n")

    print(f"\n已生成客户-顾问关联SQL")
    print(f"文件: scripts/customer_advisor_assignment.sql")

    # 统计分配情况
    print("\n分配统计：")
    stats = {}
    for assign in assignments:
        level = assign['customer_level']
        advisor_level = assign['advisor_level']
        key = f"{level} -> {advisor_level}顾问"
        stats[key] = stats.get(key, 0) + 1

    for key, count in sorted(stats.items()):
        print(f"  {key}: {count}人")

if __name__ == "__main__":
    main()
