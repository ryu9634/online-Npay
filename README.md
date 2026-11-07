# npay-auto

네이버페이 '클릭 적립' 미션을 매일 한 번 자동으로 챙긴다.

## 전제

ID/비밀번호를 코드에 넣지 않는다. 사람이 한 번 로그인해서 전용 브라우저 프로필에
세션을 남기고, 이후 실행은 그 프로필을 재사용한다. 캡차는 풀지 않고 사람을 부른다.

## 사용법

```bash
uv run src/login_once.py        # 최초 1회: 창에서 직접 로그인
uv run src/check_session.py     # 세션 유지 확인
uv run src/runner.py            # 실행 (배치 8개 동시)
uv run src/runner.py --dry-run  # 클릭 없이 대상만 확인
```

매일 23:00(±30분 지터, 최대 23:30)에 launchd 가 `run_daily.sh` 를 호출한다.

```bash
launchctl print gui/$(id -u)/com.ryu.npay-auto     # 상태
launchctl kickstart -k gui/$(id -u)/com.ryu.npay-auto   # 지금 바로 한 번
launchctl bootout gui/$(id -u)/com.ryu.npay-auto   # 중지
```

## 실측으로 확인한 네이버 쪽 제약 (2026-11-07)

이 네 가지가 설계를 결정했다. 고치기 전에 읽을 것.

1. **headless 로는 적립되지 않는다.** 브리지 페이지가 `잘못된 접근 입니다.` 를
   돌려주고 0원이 적립된다. 화면을 띄운 채 실행해야 한다.
   `runner.py` 는 `NPAY_HEADLESS=1` 이면 아예 거부한다.
2. **bridge URL 을 직접 `goto` 할 수 없다.** 같은 `잘못된 접근` 오류가 난다.
   목록 페이지에서 실제 클릭 이벤트가 나와야 한다. 그래서 "링크만 긁어서
   한꺼번에 열기"는 불가능하다.
3. **광고 페이지에 3초 이상 머물러야 적립된다.** 다만 이 체류는 탭마다 독립이므로
   여러 탭을 동시에 열면 한 번의 대기로 전부 채울 수 있다 (`--batch`).
4. **'로그인 상태 유지'를 켜야 한다.** 끄면 `NID_AUT`/`NID_SES` 가 세션 쿠키로
   내려와 브라우저를 닫는 순간 사라진다. `is_session_persistent()` 가 이걸 검사한다.

## 전체 플로우

```
목록(mission-detail) → 항목 클릭 → 새 탭에 브리지
  → 브리지 본문에 "15원이 적립돼요"
  → '포인트 받기'(a.popup_link) 클릭 → 광고 페이지로 이동
  → 3초 이상 체류 → 적립
```

- 이미 참여한 캠페인은 브리지가 **"클릭 적립은 캠페인 당 1회만 적립됩니다."** 를
  띄운다. 실패가 아니라 `건너뜀` 으로 분류한다.
- 완료한 항목은 목록에서 빠지고, `state.json` 에도 기록해 두 번 열지 않는다.

## 속도

| 모드 | 건당 | 비고 |
|---|---|---|
| `--batch 1` (순차) | 약 19초 | 가장 안전 |
| `--batch 8` (기본) | 약 8초 | 권장 |
| `--batch 20` | 더 빠름 | 패턴이 뚜렷해짐 |

체류 시간이 겹쳐서 줄어드는 것이지, 체류 자체를 건너뛰는 게 아니다.
배치를 키우면 `batch_dwell_sec` 도 같이 늘리는 게 안전하다 — 백그라운드 탭은
브라우저가 타이머를 느리게 돌린다.

## 깨졌을 때

`예상 적립` 과 `실제 잔액 변화` 가 다르면 로그와 `shots/` 스크린샷을 본다.

- 전부 `잘못된 접근` → headless 로 돌고 있다
- 전부 `'포인트 받기' 버튼을 못 찾음` → 브리지 DOM 이 바뀌었다 (`BRIDGE_BUTTON`)
- `목록 0개` → `tasks.yaml` 의 `item_selector` 가 깨졌다.
  클래스 해시(`DetailItem-module-scss-module__YUdvEa__article`)는 배포마다 바뀌므로
  반드시 `a[class*="DetailItem"]` 처럼 접두사로 매칭한다.
- 로그인 풀림 → `uv run src/login_once.py` 재실행 (보통 수 주에 한 번)

조사용으로 `uv run src/explore.py <url>` 이 페이지의 본문과 클릭 가능 요소를 덤프한다.

## 주의

- `profile/` 에는 로그인 쿠키가 들어있다. 절대 공유·커밋하지 않는다.
- 자동화로 이벤트에 참여하는 것은 네이버 이용약관에 저촉될 수 있고,
  적발 시 포인트 회수나 계정 제한이 가능하다.
  본인 계정 1개, 느린 속도, 캡차 우회 없음을 지킨다.
- `max_items_per_run` 은 안전장치다. 목록은 계속 채워지므로 이 값을 없애면
  끝없이 클릭하게 된다.

## 깃허브에 올릴 때

**절대 올라가면 안 되는 것**

- `profile/` — 네이버 로그인 쿠키(`NID_AUT`/`NID_SES`)가 들어있다.
  이게 유출되면 비밀번호 없이도 계정에 로그인된다. 2단계 인증도 소용없다.
- `shots/` — 실패 시 스크린샷. 로그인된 화면이라 이름·결제내역이 찍혀 있다.
- `logs/`, `state.json` — 포인트 잔액과 참여 이력.

`.gitignore` 가 막고 있지만, `git add -f` 나 `.gitignore` 수정으로 뚫린다.
그래서 `deploy/pre-commit` 훅이 한 번 더 막는다. 클론한 뒤에는 직접 설치해야 한다
(`.git/hooks/` 는 저장소에 포함되지 않는다):

```bash
cp deploy/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

**공개 여부**

공개 저장소로 두면 "네이버페이 포인트 자동 적립"이라는 내용 자체가 검색된다.
네이버 이용약관에 저촉될 수 있는 도구이고, 깃허브 계정으로 신원이 드러난다.
비공개(private)를 권한다.

**스케줄 등록**

`~/Library/LaunchAgents/` 의 plist 는 저장소 밖에 있다. 다른 기기에서 쓰려면:

```bash
sed "s|__PROJECT_DIR__|$PWD|g" deploy/com.npay-auto.plist.template \
  > ~/Library/LaunchAgents/com.npay-auto.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.npay-auto.plist
```

**이슈·PR 에 로그를 붙일 때**는 잔액과 adId 를 지우고 올린다.
