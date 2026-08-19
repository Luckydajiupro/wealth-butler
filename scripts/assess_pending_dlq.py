"""Read-only preflight for pending suspicious-intent EventBus messages."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from app.Base.Client.redisClient import redis_client
    from app.WealthButler.Agent.riskAgent import RiskAgent
    from app.WealthButler.EventBus.schemas import validate_event
    from app.WealthButler.Rules.ruleDefinitions import REALTIME_RULE_IDS

    client = redis_client.client
    stream = "stream:suspicious_intent"
    group = "risk_monitor_group"
    pending = client.xpending_range(stream, group, min="-", max="+", count=1000)
    outcomes: Counter[str] = Counter()
    hit_counts: Counter[int] = Counter()
    error_counts: Counter[int] = Counter()
    for item in pending:
        message_id = item.get("message_id") if isinstance(item, dict) else item[0]
        rows = client.xrange(stream, min=message_id, max=message_id, count=1)
        if not rows:
            outcomes["ORIGINAL_MISSING"] += 1
            continue
        fields = rows[0][1]
        event_type = str(fields.get("event_type", ""))
        payload = json.loads(fields.get("payload", "{}"))
        try:
            event = validate_event(event_type, payload)
            agent = RiskAgent()
            context = agent._build_context(event.customer_id)
            result = agent._match(
                event.customer_id,
                list(REALTIME_RULE_IDS),
                "event",
                context=context,
            )
        except (ValueError, TypeError) as exc:
            outcomes[f"PREFLIGHT_{type(exc).__name__}"] += 1
            continue
        outcomes[str(result.status)] += 1
        hit_counts[len(result.triggered_rules)] += 1
        error_counts[len(result.errors)] += 1
    print(json.dumps({
        "mode": "read-only-preflight",
        "pending": len(pending),
        "outcomes": dict(sorted(outcomes.items())),
        "triggered_rule_counts": dict(sorted(hit_counts.items())),
        "engine_error_counts": dict(sorted(error_counts.items())),
        "side_effects": 0,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
