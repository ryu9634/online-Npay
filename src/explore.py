"""이벤트 페이지 구조 파악용 조사 도구.

셀렉터를 추측으로 쓰면 반드시 깨지므로, 실제 DOM을 보고 쓴다.
사용: uv run src/explore.py <url> [url2 ...]
"""
from __future__ import annotations

import json
import sys

from session import browser, get_page, screenshot, setup_logging

# 클릭 후보를 뽑는 JS. 보이는 것만, 텍스트와 식별정보를 함께.
DUMP_JS = """
() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const out = [];
  const sel = 'a, button, [role=button], [onclick], input[type=submit], input[type=button]';
  for (const el of document.querySelectorAll(sel)) {
    if (!vis(el)) continue;
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
    if (!t) continue;
    out.push({
      text: t.slice(0, 60),
      tag: el.tagName.toLowerCase(),
      cls: (el.className || '').toString().slice(0, 80),
      id: el.id || null,
      href: el.getAttribute('href'),
    });
  }
  return {
    title: document.title,
    url: location.href,
    bodyText: document.body.innerText.replace(/\\n{2,}/g, '\\n').slice(0, 2500),
    clickables: out.slice(0, 120),
  };
}
"""


def main() -> int:
    setup_logging("explore")
    urls = sys.argv[1:]
    if not urls:
        print("사용: uv run src/explore.py <url> [url2 ...]")
        return 2

    with browser() as ctx:
        page = get_page(ctx)
        for url in urls:
            print(f"\n{'=' * 70}\n>>> {url}\n{'=' * 70}")
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(3500)  # 동적 렌더링 대기
                data = page.evaluate(DUMP_JS)
            except Exception as exc:
                print(f"[실패] {exc}")
                screenshot(page, "explore-fail")
                continue

            print(f"title : {data['title']}")
            print(f"final : {data['url']}")
            print(f"\n--- 본문 ---\n{data['bodyText']}")
            print(f"\n--- 클릭 가능 요소 {len(data['clickables'])}개 ---")
            for c in data["clickables"]:
                print(json.dumps(c, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
