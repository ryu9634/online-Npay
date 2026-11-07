"""날짜별 참여 기록.

같은 광고를 하루에 두 번 클릭하면 어뷰징으로 잡히기 쉽다.
목록에서 완료 항목이 빠지긴 하지만, 그것만 믿지 않고 직접 기록해 둔다.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from config import STATE_FILE


def _load() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def today_key() -> str:
    return date.today().isoformat()


def done_ad_ids(day: str | None = None) -> set[str]:
    """오늘 이미 성공 처리한 광고 ID."""
    data = _load()
    entry = data.get(day or today_key(), {})
    return set(entry.get("done", []))


def record(ad_id: str, label: str, point: int, ok: bool) -> None:
    data = _load()
    key = today_key()
    entry = data.setdefault(key, {"done": [], "failed": [], "points": 0})
    if ok:
        if ad_id not in entry["done"]:
            entry["done"].append(ad_id)
            entry["points"] = entry.get("points", 0) + point
    else:
        entry["failed"].append({"adId": ad_id, "label": label})
    _save(data)


def record_balance(before: int | None, after: int | None) -> None:
    data = _load()
    entry = data.setdefault(today_key(), {"done": [], "failed": [], "points": 0})
    entry["balance_before"] = before
    entry["balance_after"] = after
    if before is not None and after is not None:
        entry["balance_diff"] = after - before
    _save(data)


def summary(day: str | None = None) -> dict[str, Any]:
    return _load().get(day or today_key(), {})
