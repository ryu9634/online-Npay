#!/bin/bash
# launchd 가 매일 호출하는 진입점.
#
# 지터를 여기서 준다. 매일 09:00:00 정각에 접속하는 건 사람의 패턴이 아니다.
set -euo pipefail

cd "$(dirname "$0")"

UV="$(command -v uv || echo /opt/homebrew/bin/uv)"

# 0~30분 랜덤 지연
JITTER=$((RANDOM % 1800))
echo "[$(date '+%F %T')] ${JITTER}초 지터 후 시작"
sleep "$JITTER"

exec "$UV" run src/runner.py --batch 8
