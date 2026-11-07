"""브라우저 세션 관리: 영속 프로필 열기 + 로그인 상태 판정."""
from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

from config import (
    BROWSER_CHANNEL,
    DEFAULT_TIMEOUT_MS,
    HEADLESS,
    LOGIN_PROBE_URL,
    LOGS_DIR,
    PROFILE_DIR,
    SHOTS_DIR,
)

log = logging.getLogger("npay")

# navigator.webdriver 등 자동화 흔적 최소화
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US']});
"""


def setup_logging(name: str = "run") -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logfile = LOGS_DIR / f"{datetime.now():%Y-%m-%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(logfile, encoding="utf-8"), logging.StreamHandler()],
    )
    log.info("=== %s 시작 ===", name)


@contextlib.contextmanager
def browser(headless: bool | None = None) -> Iterator[BrowserContext]:
    """영속 프로필로 브라우저를 열고, 끝나면 정리한다.

    user_data_dir 에 쿠키가 남으므로 한 번 로그인하면 다음 실행에서 유지된다.
    """
    use_headless = HEADLESS if headless is None else headless
    with sync_playwright() as pw:
        launch_kwargs: dict = {
            "user_data_dir": str(PROFILE_DIR),
            "headless": use_headless,
            "locale": "ko-KR",
            "timezone_id": "Asia/Seoul",
            "viewport": None,  # 실제 창 크기를 그대로 사용
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--no-first-run",
            ],
            "ignore_default_args": ["--enable-automation"],
        }
        if BROWSER_CHANNEL:
            launch_kwargs["channel"] = BROWSER_CHANNEL

        try:
            ctx = pw.chromium.launch_persistent_context(**launch_kwargs)
        except Exception:
            log.warning("channel=%s 실행 실패 → 내장 크로미움으로 재시도", BROWSER_CHANNEL)
            launch_kwargs.pop("channel", None)
            ctx = pw.chromium.launch_persistent_context(**launch_kwargs)

        ctx.set_default_timeout(DEFAULT_TIMEOUT_MS)
        ctx.add_init_script(_STEALTH_JS)
        try:
            yield ctx
        finally:
            with contextlib.suppress(Exception):
                ctx.close()


def get_page(ctx: BrowserContext) -> Page:
    """영속 프로필은 빈 탭 하나를 갖고 열리므로 그걸 재사용한다."""
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def is_logged_in(page: Page) -> bool:
    """내 정보 페이지로 가서 로그인 페이지로 튕기는지 본다."""
    try:
        page.goto(LOGIN_PROBE_URL, wait_until="domcontentloaded")
    except Exception as exc:
        log.error("로그인 확인용 페이지 접속 실패: %s", exc)
        return False
    page.wait_for_timeout(1500)
    url = page.url
    logged_in = "nidlogin" not in url and "nid.naver.com/login" not in url
    log.info("로그인 상태: %s (url=%s)", "O" if logged_in else "X", url)
    return logged_in


def screenshot(page: Page, tag: str) -> str:
    """실패 원인 파악용. 셀렉터가 깨진 건지 로그아웃인지 구분하려면 이게 필요하다."""
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{tag}.png"
    with contextlib.suppress(Exception):
        page.screenshot(path=str(path), full_page=True)
        log.info("스크린샷: %s", path)
    return str(path)


AUTH_COOKIES = ("NID_AUT", "NID_SES")


def auth_cookie_status(ctx: BrowserContext) -> dict[str, float]:
    """로그인 쿠키의 만료값을 돌려준다.

    Playwright 는 세션 쿠키(브라우저 끄면 사라지는 것)를 expires=-1 로 준다.
    '로그인 상태 유지'를 켜지 않으면 NID_AUT/NID_SES 가 세션 쿠키로 내려오고,
    프로필에 저장돼 있는 듯 보여도 다음 실행에서 전부 사라진다.
    """
    found: dict[str, float] = {}
    for c in ctx.cookies():
        if c["name"] in AUTH_COOKIES:
            found[c["name"]] = float(c.get("expires", -1))
    return found


def is_session_persistent(ctx: BrowserContext) -> tuple[bool, str]:
    """로그인이 재실행 후에도 살아남을지 판정한다."""
    status = auth_cookie_status(ctx)
    missing = [n for n in AUTH_COOKIES if n not in status]
    if missing:
        return False, f"로그인 쿠키 없음: {', '.join(missing)}"
    ephemeral = [n for n, exp in status.items() if exp <= 0]
    if ephemeral:
        return False, (
            f"{', '.join(ephemeral)} 가 세션 쿠키입니다 — '로그인 상태 유지'가 꺼져 있습니다"
        )
    return True, "로그인 쿠키가 영속 저장되었습니다"
