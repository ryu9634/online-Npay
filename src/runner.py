"""매일 한 번 돌려서 '클릭 적립' 미션을 처리한다.

사용:
  uv run src/runner.py                  # 기본(배치 5개 동시)
  uv run src/runner.py --batch 1        # 순차 — 가장 안전하지만 느리다
  uv run src/runner.py --batch 20       # 전부 동시 — 가장 빠르지만 패턴이 뚜렷하다
  uv run src/runner.py --dry-run        # 목록만 확인
  uv run src/runner.py --limit 3        # 이번 실행만 3개로 제한
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
import time

import yaml
from playwright.sync_api import Error as PwError, Locator

import state
from clickpoint import BATCH_DWELL_SEC, detect_captcha, run_batch, run_one
from config import HEADLESS, TASKS_FILE
from notify import notify
from points import read_balance
from session import (
    browser,
    get_page,
    is_logged_in,
    is_session_persistent,
    screenshot,
    setup_logging,
)

log = logging.getLogger("npay")


def load_tasks() -> dict:
    with TASKS_FILE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def chunks(seq: list, n: int) -> list[list]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def collect_candidates(page, selector: str, already: set[str], cap: int) -> list[Locator]:
    """목록을 한 번만 읽고 아직 안 한 항목을 전부 모은다.

    항목 클릭은 새 탭을 열 뿐 목록 페이지를 떠나지 않으므로,
    매번 목록을 다시 불러올 필요가 없다 (그게 예전 방식의 주된 지연이었다).
    """
    items = page.locator(selector)
    total = items.count()
    picked: list[Locator] = []
    for i in range(total):
        if len(picked) >= cap:
            break
        it = items.nth(i)
        try:
            aid = it.evaluate("e => new URL(e.href).searchParams.get('adId')")
        except PwError:
            continue
        if aid and aid not in already:
            picked.append(it)
    log.info("목록 %d개 중 %d개가 대상", total, len(picked))
    return picked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="클릭하지 않고 목록만 확인")
    ap.add_argument("--limit", type=int, default=None, help="이번 실행의 클릭 상한")
    ap.add_argument(
        "--batch", type=int, default=None,
        help="동시에 열 탭 수. 1 이면 순차. 기본값은 tasks.yaml 의 batch_size",
    )
    ap.add_argument(
        "--dwell", type=float, default=None,
        help=f"병렬 모드 체류 시간(초). 기본 {BATCH_DWELL_SEC}",
    )
    ap.add_argument(
        "--force-headless", action="store_true",
        help="headless 강제 실행 (브리지가 '잘못된 접근'을 반환하므로 보통 실패한다)",
    )
    args = ap.parse_args()

    setup_logging("runner")

    if HEADLESS and not args.force_headless:
        log.error(
            "headless 에서는 적립되지 않습니다 (브리지가 '잘못된 접근' 반환). "
            "NPAY_HEADLESS 를 끄고 실행하세요."
        )
        return 2

    cfg = load_tasks()
    settings = cfg.get("settings", {})
    delay_lo, delay_hi = settings.get("delay_between", [4, 11])
    global_cap = args.limit or settings.get("max_items_per_run", 25)
    batch_size = args.batch or settings.get("batch_size", 5)
    dwell = args.dwell or settings.get("batch_dwell_sec", BATCH_DWELL_SEC)

    already = state.done_ad_ids()
    log.info("오늘 이미 처리한 항목: %d개 / 배치 크기 %d", len(already), batch_size)

    results: list = []
    clicked = 0
    balance_before = balance_after = None
    started = time.time()

    with browser() as ctx:
        page = get_page(ctx)

        if not is_logged_in(page):
            screenshot(page, "not-logged-in")
            notify("네이버페이 자동적립", "로그인이 풀렸습니다. login_once.py 를 실행하세요.", sound=True)
            return 3

        ok, msg = is_session_persistent(ctx)
        if not ok:
            log.warning("세션 경고: %s", msg)

        balance_before = read_balance(page)

        for placement in cfg.get("placements", []):
            if clicked >= global_cap:
                break
            name, url, sel = placement["name"], placement["url"], placement["item_selector"]
            cap = min(placement.get("max_items", global_cap), global_cap - clicked)
            log.info("--- [%s] 시작 ---", name)

            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
            except PwError as exc:
                log.error("목록 접속 실패: %s", exc)
                continue

            if detect_captcha(page):
                screenshot(page, "captcha-list")
                notify("네이버페이 자동적립", "캡차가 떴습니다. 직접 처리해 주세요.", sound=True)
                log.error("캡차 감지 — 중단")
                return 4

            candidates = collect_candidates(page, sel, already, cap)
            if not candidates:
                log.info("대상이 없습니다")
                continue

            if args.dry_run:
                for c in candidates[:5]:
                    aid = c.evaluate("e => new URL(e.href).searchParams.get('adId')")
                    log.info("[dry-run] adId=%s | %s", aid, c.inner_text().strip().replace("\n", " ")[:45])
                log.info("[dry-run] 총 %d개 대상", len(candidates))
                continue

            for group in chunks(candidates, max(1, batch_size)):
                if batch_size <= 1:
                    batch_results = [run_one(ctx, group[0])]
                else:
                    batch_results = run_batch(ctx, group, dwell_sec=dwell)

                for res in batch_results:
                    results.append(res)
                    already.add(res.ad_id)
                    # 이미 참여한 건도 '처리됨'으로 기록해 두 번 열지 않는다
                    state.record(res.ad_id, res.label, res.point, res.ok or res.already)
                    clicked += 1
                    if res.already:
                        log.info("  건너뜀 adId=%s (이미 참여) %s", res.ad_id, res.label)
                    elif not res.ok:
                        log.warning("  실패 adId=%s: %s", res.ad_id, res.reason)

                fatal = [r for r in batch_results
                         if not r.ok and ("잘못된 접근" in r.reason or "캡차" in r.reason)]
                if fatal:
                    notify("네이버페이 자동적립", f"중단: {fatal[0].reason}", sound=True)
                    log.error("치명적 오류로 중단: %s", fatal[0].reason)
                    break

                wait = random.uniform(delay_lo, delay_hi)
                log.info("  배치 간 %.1f초 대기", wait)
                time.sleep(wait)

        if not args.dry_run and clicked:
            balance_after = read_balance(page)

    if not args.dry_run and clicked:
        state.record_balance(balance_before, balance_after)

    succeeded = [r for r in results if r.ok]
    skipped = [r for r in results if r.already]
    failed = [r for r in results if not r.ok and not r.already]
    expected = sum(r.point for r in succeeded)
    actual = (
        balance_after - balance_before
        if None not in (balance_before, balance_after)
        else None
    )
    elapsed = time.time() - started

    log.info("=" * 50)
    log.info(
        "성공 %d건 / 건너뜀 %d건 / 실패 %d건 / 소요 %.0f초",
        len(succeeded), len(skipped), len(failed), elapsed,
    )
    log.info("예상 적립 %s원 / 실제 잔액 변화 %s원", expected, actual)
    if actual is not None and expected and actual != expected:
        log.warning(
            "예상과 실제 불일치 (%s vs %s) — 적립 지연이거나 일부 미반영입니다. "
            "병렬 모드라면 --dwell 을 늘리거나 --batch 를 줄여보세요.",
            expected, actual,
        )

    if not args.dry_run and clicked:
        notify(
            "네이버페이 자동적립",
            f"{len(succeeded)}건 성공 / {len(failed)}건 실패 · "
            f"{actual if actual is not None else expected}원 · {elapsed:.0f}초",
        )
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
