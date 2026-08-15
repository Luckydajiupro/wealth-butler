"""FAQ去重脚本

根据"问题+答案"组合去重，保留首次出现的问答对。
"""
import os
import sys
from pathlib import Path
from collections import OrderedDict

# 设置标准输出编码为 UTF-8
sys.stdout.reconfigure(encoding='utf-8')


def clean_faq_duplicates(faq_file_path: str) -> tuple:
    """去除FAQ文件中的重复问答对

    Args:
        faq_file_path: FAQ文件路径

    Returns:
        (unique_count, duplicate_count): 去重后的数量和重复数量
    """
    if not os.path.exists(faq_file_path):
        print(f"❌ 文件不存在: {faq_file_path}")
        return (0, 0)

    # 备份原文件
    backup_path = faq_file_path + '.backup'
    if not os.path.exists(backup_path):
        with open(faq_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✓ 原文件已备份: {backup_path}")

    # 读取文件
    with open(faq_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    print(f"\n原始行数: {len(lines)}")

    # 使用 OrderedDict 保证去重后保持原顺序
    seen = OrderedDict()
    duplicate_count = 0
    skipped_lines = []

    for line_num, line in enumerate(lines, 1):
        line = line.strip()

        # 跳过空行
        if not line:
            continue

        # 解析问题和答案
        parts = line.split('\t')
        if len(parts) != 2:
            print(f"⚠️ 第{line_num}行格式不正确（期望2列，实际{len(parts)}列），跳过")
            skipped_lines.append(line_num)
            continue

        question = parts[0].strip()
        answer = parts[1].strip()

        # 去重键：问题+答案
        key = (question, answer)

        if key not in seen:
            seen[key] = line
        else:
            duplicate_count += 1
            print(f"[去重] 第{line_num}行重复: {question[:50]}...")

    # 写回文件
    unique_lines = list(seen.values())
    with open(faq_file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(unique_lines))
        if unique_lines:
            f.write('\n')  # 文件末尾换行

    # 输出统计
    print("\n" + "=" * 80)
    print("FAQ 去重完成")
    print("=" * 80)
    print(f"✓ 原始条数: {len(lines)}")
    print(f"✓ 保留条数: {len(unique_lines)}")
    print(f"✓ 删除重复: {duplicate_count} 条")
    if skipped_lines:
        print(f"⚠️ 格式错误行号: {skipped_lines}")
    print("=" * 80 + "\n")

    return (len(unique_lines), duplicate_count)


if __name__ == '__main__':
    # FAQ文件路径
    faq_path = 'D:/lqh/金融/公司信息/高频问答对.txt'

    # 执行去重
    unique_count, duplicate_count = clean_faq_duplicates(faq_path)

    # 验证结果
    if unique_count > 0:
        print(f"✅ 去重成功！当前文件包含 {unique_count} 条唯一问答对")
    else:
        print("❌ 去重失败，请检查文件路径和格式")
