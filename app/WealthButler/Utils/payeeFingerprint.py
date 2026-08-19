"""受信收款方指纹的唯一规范实现。

写入与核验必须共享相同的 Unicode 归一化和 HMAC 消息格式；拆成独立工具可避免
任一端局部修改后造成全部真实收款方无法匹配。
"""

from __future__ import annotations

import hashlib
import hmac
import unicodedata


def normalize_account(account: str) -> str:
    if not isinstance(account, str):
        raise TypeError("account 必须是字符串")
    normalized = unicodedata.normalize("NFKC", account)
    return "".join(
        character
        for character in normalized
        if not character.isspace() and character != "-"
    )


def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError("name 必须是字符串")
    return " ".join(unicodedata.normalize("NFKC", name).strip().casefold().split())


def fingerprint(
    secret: str,
    scope: str,
    customer_id: int,
    normalized_value: str,
) -> str:
    if not isinstance(secret, str) or not secret:
        raise ValueError("HMAC secret 不能为空")
    if not isinstance(scope, str) or not scope:
        raise ValueError("fingerprint scope 不能为空")
    if not isinstance(customer_id, int) or isinstance(customer_id, bool) or customer_id <= 0:
        raise ValueError("customer_id 必须为正整数")
    if not isinstance(normalized_value, str) or not normalized_value:
        raise ValueError("normalized_value 不能为空")
    message = f"{scope}:{customer_id}:{normalized_value}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


__all__ = ["fingerprint", "normalize_account", "normalize_name"]
