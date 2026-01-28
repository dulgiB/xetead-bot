from battle.core.commands.define import RoundPhaseType

STAT_RULES = """**스탯 분배 규칙**
초기 포인트: **10pt** (마일스톤마다 +3pt, 전체 재분배 가능)

| 스탯 | 기본값 | 상한 | 포인트 비용 |
|------|--------|------|------------|
| 공격력 | 3 | 12 | +1당 2pt |
| 체력 | 60 | 100 | +10당 1pt |
| 사거리 | 1 | 3 | +1당 4pt |

**대미지 공식**: 공격력 + Nd6 (N은 마일스톤)

**마법 저항** (종족 고정)
- `낮음`: 마법 대미지 +10% / 추가 4pt
- `보통`: 변동 없음 / 추가 1pt
- `높음`: 마법 대미지 −10% / 추가 없음
"""

SKILL_HELP = (
    "스킬 설정: `/스킬 캐릭터이름:... 패시브:ID 스킬1:ID 스킬2:ID`\n"
    "각 슬롯은 생략 가능합니다. `/스킬목록` `/버프목록`으로 ID를 확인하세요."
)

# 마지막 활동으로부터 이 시간(초) 이상 경과하면 세션을 자동 종료한다.
SESSION_TIMEOUT_SECONDS = 60 * 60 * 3  # 3시간
# 만료 검사 주기 (분)
CLEANUP_INTERVAL_MINUTES = 30

PHASE_ORDER: list[RoundPhaseType] = [
    RoundPhaseType.ENEMY_PRE_ACTION,
    RoundPhaseType.ALLY_ACTION,
    RoundPhaseType.ENEMY_POST_ACTION,
    RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY,
]

PHASE_NAMES: dict[RoundPhaseType, str] = {
    RoundPhaseType.ENEMY_PRE_ACTION: "🔴 적 행동 선언",
    RoundPhaseType.ALLY_ACTION: "🔵 아군 행동",
    RoundPhaseType.ENEMY_POST_ACTION: "🔴 적 공격 정산",
    RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY: "⏳ 라운드 종료",
}
