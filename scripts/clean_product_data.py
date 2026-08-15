"""产品数据清洗脚本

1. 创建产品信息映射表（产品名称 → risk_level, product_code）
2. 清除占位符
3. 检查残留占位符
"""
import os
import sys
import json
import re
import hashlib
from pathlib import Path

# 设置标准输出编码为 UTF-8
sys.stdout.reconfigure(encoding='utf-8')


# ============================================================
# 产品信息映射表（从产品手册提取）
# ============================================================

PRODUCT_INFO_MAPPING = {
    # 货币基金
    'XX货币市场基金': {
        'risk_level': 'R1',
        'product_type': '货币市场基金',
        'product_code': None  # 手册中也是占位符，需生成
    },

    # 债券基金
    'XX稳健增利债券A': {
        'risk_level': 'R2',
        'product_type': '纯债债券型基金',
        'product_code': None
    },

    # 混合基金
    'XX平衡优选混合': {
        'risk_level': 'R3',
        'product_type': '偏股混合型基金',
        'product_code': None
    },

    # 股票基金
    'XX科技创新股票': {
        'risk_level': 'R4',
        'product_type': '股票型基金',
        'product_code': None
    },

    'XX全球精选QDII': {
        'risk_level': 'R4',
        'product_type': 'QDII股票型基金',
        'product_code': None
    },

    'XX红利价值股票': {
        'risk_level': 'R3',
        'product_type': '股票型基金',
        'product_code': None
    },

    # 银行理财
    'XX季季盈90天': {
        'risk_level': 'R2',
        'product_type': '固定收益类银行理财',
        'product_code': None
    },

    'XX年年盈365天': {
        'risk_level': 'R3',
        'product_type': '固定收益类银行理财',
        'product_code': None
    },

    'XX结构性存款': {
        'risk_level': 'R2',
        'product_type': '结构性存款',
        'product_code': None
    },

    # 保险产品
    'XX福享年金保险': {
        'risk_level': 'R2',
        'product_type': '年金保险',
        'product_code': None
    },

    'XX传世增额终身寿险': {
        'risk_level': 'R2',
        'product_type': '增额终身寿险',
        'product_code': None
    }
}


def generate_product_code(product_name: str) -> str:
    """生成临时产品代码（基于MD5哈希）

    Args:
        product_name: 产品名称

    Returns:
        6位大写字母数字组合，格式：JPXXXX
    """
    hash_obj = hashlib.md5(product_name.encode('utf-8'))
    hash_hex = hash_obj.hexdigest()
    # 取前6位转大写
    code = 'JP' + hash_hex[:4].upper()
    return code


def load_placeholder_dict(dict_path: str) -> dict:
    """加载占位符字典"""
    with open(dict_path, 'r', encoding='utf-8') as f:
        placeholder_dict = json.load(f)
    print(f"已加载占位符字典: {len(placeholder_dict)} 条规则")
    return placeholder_dict


def clean_placeholders(text: str, placeholder_dict: dict) -> str:
    """使用占位符字典清洗文本

    Args:
        text: 原始文本
        placeholder_dict: 占位符替换字典

    Returns:
        清洗后的文本
    """
    cleaned_text = text

    # 按照字典顺序替换（长占位符优先）
    sorted_items = sorted(placeholder_dict.items(), key=lambda x: len(x[0]), reverse=True)

    for placeholder, replacement in sorted_items:
        cleaned_text = cleaned_text.replace(placeholder, replacement)

    return cleaned_text


def check_remaining_placeholders(text: str) -> dict:
    """检查残留的占位符

    Returns:
        {placeholder_pattern: count}
    """
    remaining = {}

    # 检查常见占位符模式
    patterns = {
        'XX': r'\bXX\b',  # 独立的XX
        'XXX': r'\bXXX\b',  # 独立的XXX
        'XXXX': r'\bXXXX\b',  # 独立的XXXX
        'XXXXXX': r'\bXXXXX+\b',  # 5个及以上X
        'X万': r'X万',
        'X亿': r'X亿',
        'X,XXX': r'X,XXX',
        'XX,XXX': r'XX,XXX',
        'XXX万': r'XXX万(?!人)',  # 排除 "XXX万人"（已在字典中）
        'XXX亿': r'XXX亿(?!元)',  # 排除 "XXX亿元"（已在字典中）
        'X月': r'X月',
        'XX月': r'XX月',
        'XX日': r'XX日',
        'XX%': r'XX%',
        '某市': r'某市',
        '某某': r'某某',
        '王某': r'[王李张赵刘陈]某',  # 人名占位符
    }

    for name, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            remaining[name] = len(matches)

    return remaining


def clean_product_file(product_file_path: str, placeholder_dict_path: str, output_path: str = None):
    """清理产品文件中的占位符

    Args:
        product_file_path: 产品手册路径
        placeholder_dict_path: 占位符字典路径
        output_path: 输出路径（None则覆盖原文件）
    """
    print("\n" + "=" * 80)
    print("产品数据清洗")
    print("=" * 80)

    # 1. 备份原文件
    backup_path = product_file_path + '.backup'
    if not os.path.exists(backup_path):
        with open(product_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"原文件已备份: {backup_path}")

    # 2. 加载占位符字典
    placeholder_dict = load_placeholder_dict(placeholder_dict_path)

    # 3. 读取产品文件
    with open(product_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"原文件大小: {len(content)} 字符")

    # 4. 替换占位符
    cleaned_content = clean_placeholders(content, placeholder_dict)

    # 5. 检查残留占位符
    print("\n检查残留占位符...")
    remaining = check_remaining_placeholders(cleaned_content)

    if remaining:
        print("\n警告：发现残留占位符")
        print("-" * 80)
        for pattern, count in sorted(remaining.items(), key=lambda x: x[1], reverse=True):
            print(f"  {pattern}: {count} 处")
        print("-" * 80)
    else:
        print("未发现残留占位符")

    # 6. 写回文件
    output_path = output_path or product_file_path
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(cleaned_content)

    print(f"\n清洗后文件已保存: {output_path}")
    print(f"清洗后大小: {len(cleaned_content)} 字符")
    print("=" * 80 + "\n")

    return remaining


def save_product_mapping(output_path: str):
    """保存产品信息映射表（补齐product_code）"""
    print("生成产品信息映射表...")

    # 为每个产品生成product_code
    for product_name, info in PRODUCT_INFO_MAPPING.items():
        if info['product_code'] is None:
            info['product_code'] = generate_product_code(product_name)

    # 保存为JSON
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(PRODUCT_INFO_MAPPING, f, ensure_ascii=False, indent=2)

    print(f"产品信息映射表已保存: {output_path}")
    print(f"包含 {len(PRODUCT_INFO_MAPPING)} 个产品\n")

    # 打印映射表
    print("产品信息映射表:")
    print("-" * 80)
    for product_name, info in PRODUCT_INFO_MAPPING.items():
        print(f"  {product_name}")
        print(f"    - 风险等级: {info['risk_level']}")
        print(f"    - 产品类型: {info['product_type']}")
        print(f"    - 产品代码: {info['product_code']}")
    print("-" * 80 + "\n")


if __name__ == '__main__':
    # 文件路径
    product_file = 'D:/lqh/金融/公司业务/个人理财产品手册.md'
    placeholder_dict_file = 'D:/lqh/金融/scripts/placeholder_dict.json'
    product_mapping_output = 'D:/lqh/金融/scripts/product_info_mapping.json'

    # 1. 保存产品信息映射表
    save_product_mapping(product_mapping_output)

    # 2. 清洗产品文件
    remaining = clean_product_file(product_file, placeholder_dict_file)

    # 3. 输出清洗报告
    if remaining:
        print("需要补充的占位符规则:")
        print("-" * 80)
        for pattern, count in remaining.items():
            print(f"  \"{pattern}\": \"[需要人工补充真实值]\"")
        print("-" * 80)
        print("\n建议：将上述占位符补充到 placeholder_dict.json 后重新运行清洗")
    else:
        print("清洗完成！未发现残留占位符")
