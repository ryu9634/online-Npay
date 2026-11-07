"""포인트 잔액 읽기.

'돌긴 돌았는데 적립은 안 됨' 상태를 잡아내려면 실행 전후 잔액 비교가 필요하다.
"""
from __future__ import annotations

import logging
import re

from playwright.sync_api import Page

log = logging.getLogger("npay")

BALANCE_URL = "https://point.pay.naver.com/pointshistory/list?category=all"

# "내 포인트\n12,345원" 형태
_BALANCE_RE = re.compile(r"내\s*포인트\s*([\d,]+)\s*원")


def read_balance(page: Page) -> int | None:
    """현재 포인트 잔액(원). 못 읽으면 None."""
    try:
        page.goto(BALANCE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        body = page.evaluate("() => document.body.innerText")
    except Exception as exc:
        log.error("잔액 페이지 접속 실패: %s", exc)
        return None

    m = _BALANCE_RE.search(body)
    if not m:
        log.warning("잔액 패턴을 찾지 못했습니다 (페이지 구조 변경 가능)")
        return None
    value = int(m.group(1).replace(",", ""))
    log.info("포인트 잔액: %s원", f"{value:,}")
    return value
