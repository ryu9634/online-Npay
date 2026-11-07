"""최초 1회 수동 로그인.

브라우저를 띄워주고, 사람이 직접 로그인할 때까지 기다린다.
ID/비밀번호를 코드가 입력하지 않는다 — 캡차·기기인증을 자동으로 넘기려 하면
계정이 막히고, 그게 이 방식의 핵심 전제다.
"""
from __future__ import annotations

import sys
import time

from config import LOGIN_PAGE_URL, PROFILE_DIR
from session import browser, get_page, is_logged_in, is_session_persistent, setup_logging

WAIT_LIMIT_SEC = 600  # 10분


def main() -> int:
    setup_logging("login_once")
    print(f"\n프로필 경로: {PROFILE_DIR}")
    print("브라우저가 열립니다. 창에서 직접 네이버에 로그인하세요.")
    print("  · '로그인 상태 유지'를 반드시 켜 주세요 (세션이 훨씬 오래 갑니다)")
    print("  · 2단계 인증·기기 등록이 나오면 그것도 끝까지 완료하세요")
    print(f"  · 최대 {WAIT_LIMIT_SEC // 60}분간 기다립니다\n")

    with browser(headless=False) as ctx:
        page = get_page(ctx)

        if is_logged_in(page):
            ok, msg = is_session_persistent(ctx)
            print(f"이미 로그인된 상태입니다. ({msg})")
            return 0 if ok else 2

        page.goto(LOGIN_PAGE_URL, wait_until="domcontentloaded")

        deadline = time.time() + WAIT_LIMIT_SEC
        while time.time() < deadline:
            page.wait_for_timeout(3000)
            url = page.url
            # 로그인에 성공하면 nid 도메인을 벗어난다
            if "nid.naver.com" not in url:
                page.wait_for_timeout(2000)
                if is_logged_in(page):
                    ok, msg = is_session_persistent(ctx)
                    if ok:
                        print(f"\n로그인 성공. {msg}")
                        print("`uv run src/check_session.py` 로 확인하세요.")
                        return 0
                    print(f"\n[경고] 로그인은 됐지만 유지되지 않습니다: {msg}")
                    print("브라우저를 닫는 순간 로그인이 사라집니다.")
                    print("로그아웃 후 '로그인 상태 유지'를 켜고 다시 로그인하세요.")
                    return 2
            remaining = int(deadline - time.time())
            print(f"  대기 중... ({remaining}초 남음)", end="\r", flush=True)

        print("\n시간이 초과되었습니다. 다시 실행해 주세요.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
