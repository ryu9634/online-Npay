"""'클릭 적립' 미션 수행. 순차 모드와 병렬(배치) 모드 둘 다 지원한다.

실제로 확인한 플로우 (2026-11-07):
  1) 목록 항목(a[class*=DetailItem])을 클릭 → 새 탭에 브리지 페이지
  2) 브리지 본문에 "15원이 적립돼요" 로 적립액이 적혀 있다
  3) 브리지의 '포인트 받기'(a.popup_link) 클릭 → 같은 탭이 광고 페이지로 이동
  4) 그 페이지에 3초 이상 머물러야 적립

확인된 제약:
  · headless 불가 — 브리지가 '잘못된 접근 입니다.' 를 돌려준다
  · bridge URL 직접 goto 불가 — 같은 오류. 페이지에서 실제 클릭이 필요하다
  · 체류 3초는 탭별로 독립이므로, 여러 탭을 동시에 열어 한 번에 채울 수 있다
"""
from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field

from playwright.sync_api import BrowserContext, Error as PwError, Locator, Page

from session import screenshot

log = logging.getLogger("npay")

STATUS_API = "campaign2-api.naver.com/click-point/v2/status"
BRIDGE_BUTTON = "a.popup_link"
BAD_ACCESS = "잘못된 접근"
CAPTCHA_HINTS = ("자동입력 방지", "보안문자", "captcha", "비정상적인 접근")
# 이미 참여한 캠페인을 다시 열면 뜨는 문구. 실패가 아니라 "오늘은 끝"이라는 뜻이다.
ALREADY_HINTS = ("1회만 적립", "이미 적립", "이미 참여", "참여 완료")

DWELL_SEC = (4.0, 7.0)          # 순차 모드 체류 (요구치 3초 + 여유)
BATCH_DWELL_SEC = 12.0          # 병렬 모드 체류. 백그라운드 탭은 타이머가
                                # 느려질 수 있어 넉넉히 둔다.

_POINT_RE = re.compile(r"(\d+)\s*원이\s*적립")
_POINT_JSON_RE = re.compile(r'"point"\s*:\s*(\d+)')


@dataclass
class ClickResult:
    ad_id: str
    label: str
    ok: bool
    point: int = 0
    reason: str = ""
    already: bool = False  # 이미 참여한 캠페인 (실패 아님)


@dataclass
class Pending:
    """브리지를 열고 '포인트 받기'까지 누른 뒤 체류를 기다리는 항목."""
    ad_id: str
    label: str
    page: Page
    point: int = 0
    claimed: bool = False
    reason: str = ""
    already: bool = False
    extra: list = field(default_factory=list)


def detect_captcha(page: Page) -> bool:
    try:
        body = page.evaluate("() => document.body.innerText")
    except PwError:
        return False
    low = body.lower()
    return any(h.lower() in low for h in CAPTCHA_HINTS)


def _item_meta(item: Locator) -> tuple[str, str]:
    ad_id = item.evaluate("e => new URL(e.href).searchParams.get('adId')") or "?"
    label = item.inner_text().strip().replace("\n", " ")[:45]
    return ad_id, label


def _point_of(bridge: Page) -> int:
    """브리지 본문에서 적립액을 읽는다. 동시에 여러 탭을 열어도 섞이지 않는다."""
    try:
        body = bridge.evaluate("() => document.body.innerText")
    except PwError:
        return 0
    m = _POINT_RE.search(body)
    return int(m.group(1)) if m else 0


def _open_bridge(item: Locator) -> Pending:
    """항목을 클릭해서 브리지 탭을 연다. 클릭만 하고 체류는 하지 않는다."""
    ad_id, label = _item_meta(item)
    with item.page.expect_popup(timeout=20_000) as info:
        item.click()
    bridge = info.value
    bridge.wait_for_load_state("domcontentloaded")
    return Pending(ad_id=ad_id, label=label, page=bridge)


def _claim(p: Pending) -> None:
    """브리지의 '포인트 받기'를 눌러 광고 페이지로 이동시킨다 (체류는 호출자가 담당).

    버튼이 보일 때까지 기다린 뒤에 적립액을 읽는다. 브리지 본문은 JS 로 그려지므로
    고정 시간만 기다리면 아직 비어 있는 경우가 있다.
    """
    bridge = p.page

    btn = bridge.locator(BRIDGE_BUTTON).first
    try:
        btn.wait_for(state="visible", timeout=12_000)
    except PwError:
        btn = bridge.get_by_text("포인트 받기", exact=False).first
        try:
            btn.wait_for(state="visible", timeout=4_000)
        except PwError:
            body = bridge.evaluate("() => document.body.innerText")
            if any(h in body for h in ALREADY_HINTS):
                p.already = True
                p.reason = "이미 참여한 캠페인"
            elif BAD_ACCESS in body:
                screenshot(bridge, f"badaccess-{p.ad_id}")
                p.reason = "브리지가 '잘못된 접근' — headless 실행 가능성"
            elif detect_captcha(bridge):
                screenshot(bridge, f"captcha-{p.ad_id}")
                p.reason = "캡차 발생"
            else:
                screenshot(bridge, f"nobutton-{p.ad_id}")
                p.reason = "'포인트 받기' 버튼을 못 찾음"
            return

    body = bridge.evaluate("() => document.body.innerText")
    if BAD_ACCESS in body:
        screenshot(bridge, f"badaccess-{p.ad_id}")
        p.reason = "브리지가 '잘못된 접근' — headless 실행 가능성"
        return
    if detect_captcha(bridge):
        screenshot(bridge, f"captcha-{p.ad_id}")
        p.reason = "캡차 발생"
        return

    # 버튼이 보이는 지금 읽어야 한다. 클릭 후에는 광고 페이지로 바뀌어 사라진다.
    p.point = _point_of(bridge)
    if p.point == 0:
        log.debug("adId=%s 적립액을 못 읽음 (본문: %r)", p.ad_id, body[:80])

    btn.click(timeout=10_000)
    p.claimed = True


def _close_all_but_first(ctx: BrowserContext) -> None:
    for pg in list(ctx.pages)[1:]:
        try:
            pg.close()
        except PwError:
            pass


def run_one(ctx: BrowserContext, item: Locator) -> ClickResult:
    """항목 하나를 순차로 끝까지 처리한다."""
    try:
        p = _open_bridge(item)
    except PwError as exc:
        return ClickResult("?", "?", False, reason=f"브리지 열기 실패: {exc}"[:200])

    try:
        p.page.wait_for_timeout(2000)
        _claim(p)
        if not p.claimed:
            return ClickResult(p.ad_id, p.label, False, reason=p.reason, already=p.already)

        dwell = random.uniform(*DWELL_SEC)
        p.page.wait_for_timeout(int(dwell * 1000))

        if detect_captcha(p.page):
            screenshot(p.page, f"captcha-dest-{p.ad_id}")
            return ClickResult(p.ad_id, p.label, False, reason="광고 페이지에서 캡차")

        log.info("  적립 adId=%s (+%s원, 체류 %.1fs) %s", p.ad_id, p.point, dwell, p.label)
        return ClickResult(p.ad_id, p.label, True, point=p.point)
    except PwError as exc:
        screenshot(p.page, f"error-{p.ad_id}")
        return ClickResult(p.ad_id, p.label, False, reason=f"{type(exc).__name__}: {exc}"[:200])
    finally:
        _close_all_but_first(ctx)


def run_batch(
    ctx: BrowserContext,
    items: list[Locator],
    dwell_sec: float = BATCH_DWELL_SEC,
    open_gap: tuple[float, float] = (0.4, 1.2),
) -> list[ClickResult]:
    """여러 항목을 동시에 열어 체류 시간을 겹친다.

    체류 3초는 탭마다 독립이므로, N개를 열어두면 N배 빨라진다.
    탭을 여는 간격(open_gap)은 완전히 0으로 두지 않는다 — 동일 밀리초에
    20개 요청이 나가는 건 사람의 행동이 아니다.
    """
    pending: list[Pending] = []

    # 1단계: 전부 열고 '포인트 받기'까지 누른다
    for item in items:
        try:
            p = _open_bridge(item)
        except PwError as exc:
            pending.append(
                Pending(ad_id="?", label="?", page=None, reason=f"열기 실패: {exc}"[:150])  # type: ignore[arg-type]
            )
            continue
        pending.append(p)
        try:
            _claim(p)  # 내부에서 버튼이 보일 때까지 대기
        except PwError as exc:
            p.reason = f"{type(exc).__name__}: {exc}"[:150]
        time.sleep(random.uniform(*open_gap))

    claimed = [p for p in pending if p.claimed]
    log.info("  %d개 탭 동시 개방 — %.1f초 함께 체류", len(claimed), dwell_sec)

    # 2단계: 한 번만 기다린다. 모든 탭이 동시에 체류 조건을 채운다.
    time.sleep(dwell_sec)

    # 3단계: 결과 수집
    results: list[ClickResult] = []
    for p in pending:
        if not p.claimed:
            results.append(
                ClickResult(p.ad_id, p.label, False,
                            reason=p.reason or "미확인", already=p.already)
            )
            continue
        if detect_captcha(p.page):
            screenshot(p.page, f"captcha-dest-{p.ad_id}")
            results.append(ClickResult(p.ad_id, p.label, False, reason="광고 페이지에서 캡차"))
            continue
        log.info("  적립 adId=%s (+%s원) %s", p.ad_id, p.point, p.label)
        results.append(ClickResult(p.ad_id, p.label, True, point=p.point))

    _close_all_but_first(ctx)
    return results
