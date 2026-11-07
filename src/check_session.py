"""저장된 프로필로 세션이 유지되는지 확인한다.

1단계의 성패를 가르는 스크립트. 여기가 통과해야 나머지 설계가 성립한다.
"""
from __future__ import annotations

import sys

from session import (
    browser,
    get_page,
    is_logged_in,
    is_session_persistent,
    screenshot,
    setup_logging,
)


def main() -> int:
    setup_logging("check_session")
    headless = "--headless" in sys.argv

    with browser(headless=headless) as ctx:
        page = get_page(ctx)
        ok = is_logged_in(page)
        if ok:
            persistent, msg = is_session_persistent(ctx)
            print(f"\n세션 유지 OK (headless={headless})")
            print(f"쿠키 영속성: {'OK' if persistent else 'NG'} — {msg}")
            return 0 if persistent else 2
        screenshot(page, "session-expired")
        print("\n세션이 없습니다. `uv run src/login_once.py` 를 먼저 실행하세요.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
