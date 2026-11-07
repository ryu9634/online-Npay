"""경로와 공통 설정."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROFILE_DIR = ROOT / "profile"      # 브라우저 사용자 데이터(쿠키/세션)
LOGS_DIR = ROOT / "logs"            # 일자별 실행 로그
SHOTS_DIR = ROOT / "shots"          # 실패 시 스크린샷
STATE_FILE = ROOT / "state.json"    # 날짜별 참여 기록
TASKS_FILE = ROOT / "tasks.yaml"    # 이벤트 정의

for _d in (PROFILE_DIR, LOGS_DIR, SHOTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# 로그인 여부를 판정할 때 쓰는 페이지. 비로그인이면 nidlogin.login 으로 리다이렉트된다.
LOGIN_PROBE_URL = "https://nid.naver.com/user2/help/myInfo?lang=ko_KR"
LOGIN_PAGE_URL = "https://nid.naver.com/nidlogin.login"

# 실제 크롬을 쓸지(권장) 아니면 Playwright 내장 크로미움을 쓸지.
BROWSER_CHANNEL = os.environ.get("NPAY_BROWSER_CHANNEL", "chrome")

# 화면을 띄울지. 네이버는 headless 를 탐지하므로 기본은 띄우는 쪽.
HEADLESS = os.environ.get("NPAY_HEADLESS", "0") == "1"

DEFAULT_TIMEOUT_MS = 20_000
