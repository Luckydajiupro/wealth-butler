#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""调试Union类型检测"""

from typing import Optional, Union, get_origin, get_args

# 测试Optional[int]的结构
opt_int = Optional[int]
print(f"Optional[int]: {opt_int}")
print(f"get_origin: {get_origin(opt_int)}")
print(f"get_args: {get_args(opt_int)}")
print(f"type(Optional[int]): {type(Optional[int])}")
print(f"get_origin(opt_int) is Union: {get_origin(opt_int) is Union}")

# 正确的检测方式
origin = get_origin(opt_int)
if origin is Union:
    args = get_args(opt_int)
    non_none_types = [arg for arg in args if arg is not type(None)]
    print(f"\n过滤后的类型: {non_none_types}")
    if non_none_types:
        actual_type = non_none_types[0]
        print(f"实际类型: {actual_type}")
        print(f"是int吗: {actual_type is int}")
