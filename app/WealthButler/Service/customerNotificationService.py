"""Reliable, idempotent Redis delivery for customer-facing work-order results."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Mapping


def store_work_order_result_notification(payload: Mapping[str, Any], trace_id: str) -> bool:
    from app.Base.Client.redisClient import redis_client

    event_id = str(payload.get("event_id") or "").strip()
    customer_id = int(payload.get("customer_id") or 0)
    if not event_id or customer_id <= 0:
        raise ValueError("工单结果通知缺少 event_id 或 customer_id")

    dedupe_key = f"notification:work-order-result:{event_id}"
    inserted = redis_client.client.set(dedupe_key, "1", nx=True, ex=7 * 24 * 3600)
    if not inserted:
        return False

    notification = {
        "id": event_id,
        "event_id": event_id,
        "type": "work_order_result",
        "order_id": payload.get("order_id"),
        "customer_id": customer_id,
        "business_subtype": payload.get("business_subtype"),
        "session_id": payload.get("session_id"),
        "status": payload.get("status"),
        "message": str(payload.get("reply") or ""),
        "handler_id": payload.get("handler_id"),
        "handler_name": payload.get("handler_name"),
        "trace_id": trace_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    key = f"notifications:user:{customer_id}"
    try:
        redis_client.client.lpush(key, json.dumps(notification, ensure_ascii=False))
        redis_client.client.ltrim(key, 0, 99)
        redis_client.client.expire(key, 7 * 24 * 3600)
    except Exception:
        redis_client.client.delete(dedupe_key)
        raise
    return True
