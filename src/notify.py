"""알림. 캡차가 뜨면 사람을 불러야 하므로 꼭 필요하다."""
from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("npay")


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str, sound: bool = False) -> None:
    """맥 알림센터로 알린다. 실패해도 본 작업을 막지 않는다."""
    log.info("[알림] %s — %s", title, message)
    osascript = shutil.which("osascript")
    if not osascript:
        return
    script = (
        f'display notification "{_escape(message)}" '
        f'with title "{_escape(title)}"'
    )
    if sound:
        script += ' sound name "Submarine"'
    try:
        subprocess.run([osascript, "-e", script], timeout=10, check=False)
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("알림 실패: %s", exc)
