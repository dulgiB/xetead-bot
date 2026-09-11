from enum import Enum

CHARACTER_PER_COLUMN = 3
MAX_SKILL_SLOT_COUNT = 3
MAX_EFFECT_COUNT = 3
MAX_PASSIVE_EFFECT_COUNT = 3

# --- 운명간섭(플레이어 표기: "키워드 보정") ---------------------------------
# 부활 경험이 있는 캐릭터가 커맨드에 "+" 접미사를 붙여 굴림을 끌어올리는 기능.
# 대가로 체력을 소모하며, 스토리 진행(전투) 1회당 1번만 쓸 수 있다.
FATE_INTERVENTION_HP_COST = 20
# 비전투 판정([판정+/스탯])에 더해지는 고정 보정.
FATE_INTERVENTION_ROLL_BONUS = 3
# 기본 공격([공격+/대상])의 공격 굴림에 더해지는 보정. 고정 대미지와 달리
# 주는/받는 대미지 배율이 곱해지기 전에 더해지므로 배율 보정을 함께 받는다.
FATE_INTERVENTION_ATTACK_BONUS = 15
# 대미지 스킬의 굴림 보정. fate_mode를 비워 둔 스킬이 쓰는 기본값이다.
FATE_INTERVENTION_SKILL_BONUS = 10
FATE_INTERVENTION_REQUIRED_REVIVAL_COUNT = 1

# --- 부활 횟수 --------------------------------------------------------------
# revival_count는 GM이 시트에서 직접 관리한다 — 봇은 배치 시점에 읽어 아래
# 수치 효과에만 반영하고 값을 갱신하지 않는다. 부활 횟수에 따른 스킬 강화도
# GM이 스킬 슬롯을 바꾸는 운영 처리라 코드에 게이트가 없다.
#
# 단위는 퍼센트 포인트.
REVIVAL_RECEIVED_DAMAGE_PERCENT_PER_COUNT = 10
# 이 횟수 이상이면 턴당 코스트가 +1 되고, 대신 모든 이동 커맨드의 코스트도 +1 된다.
REVIVAL_COUNT_FOR_EXTRA_COST = 4


class BattlefieldColumnIndex(Enum):
    NONE = 7

    COL1 = 0
    COL2 = 1
    COL3 = 2
    COL4 = 3
    COL5 = 4
    COL6 = 5
    COL7 = 6

    def __str__(self):
        if self.value == 7:
            return "-"
        return str(self.value + 1)

    @classmethod
    def from_str(cls, input_str: str):
        mapping: dict[str, "BattlefieldColumnIndex"] = {
            "1열": cls.COL1,
            "1": cls.COL1,
            "2열": cls.COL2,
            "2": cls.COL2,
            "3열": cls.COL3,
            "3": cls.COL3,
            "4열": cls.COL4,
            "4": cls.COL4,
            "5열": cls.COL5,
            "5": cls.COL5,
            "6열": cls.COL6,
            "6": cls.COL6,
            "7열": cls.COL7,
            "7": cls.COL7,
        }
        if input_str in mapping:
            return mapping[input_str]
        raise ValueError(input_str)


class FactionType(str, Enum):
    ALLY = "아군"
    ENEMY = "적군"


class CombatStatType(str, Enum):
    ATK = "공격력"
    RANGE = "사거리"
    MAX_HP = "최대 체력"
    COST_PER_TURN = "턴당 코스트"


class ValueSourceType(str, Enum):
    FIXED = "고정값"

    STAT_ATK = "공격력"
    STAT_ATK_ROLL = "공격 굴림값"
    STAT_RANGE = "사거리"
    STAT_MAX_HP = "최대 체력"
    STAT_COST_PER_TURN = "턴당 코스트"

    SELF_CURR_HP = "자신의 현재 체력"
    SELF_CURR_POSITION = "자신의 현재 위치"
    TARGET_CURR_HP = "상대의 현재 체력"
    TARGET_MAX_HP = "상대의 최대 체력"
    TARGET_CURR_POSITION = "상대의 현재 위치"

    GIVEN_DAMAGE = "해당 공격으로 입힌 대미지"
    GIVEN_HEAL = "해당 행동으로 부여한 회복량"
    CONSUMED_BUFF_STACK = "해당 행동으로 소모한 버프 스택 수"
    INCREASED_BUFF_STACK = "해당 행동으로 증가한 버프 스택 수"
    # CONSUMED_BUFF_STACK과 달리 스택을 소모하지 않고 읽기만 한다 —
    # 라운드 종료 DoT처럼 스택을 남긴 채 비례 대미지를 낼 때 쓴다.
    REFERENCED_BUFF_STACK = "참조 버프의 현재 스택 수"

    TOWARD_HOLDER = "공격자 방향으로"
    AWAY_FROM_HOLDER = "공격자 반대 방향으로"

    INPUT_COLUMN = "지정한 열"


class ValueType(str, Enum):
    INTEGER = "정수"
    PERCENT = "퍼센트"


class MagicResistanceType(str, Enum):
    WEAK = "낮음"
    NORMAL = "보통"
    STRONG = "높음"


class BuffTargetType(str, Enum):
    DAMAGE = "대미지"
    HEAL = "회복"
    COST = "코스트"


class ActionType(str, Enum):
    ADMIN = "시스템 커맨드"
    MOVE = "이동"
    ATTACK = "공격"
    SKILL = "스킬"
    USE_ITEM = "아이템"


class ItemType(str, Enum):
    # 전투용 스테이터스/효과를 가지되 전투 밖에서도 사용 가능. 비전투 사용 시
    # 코스트/사거리는 무시된다.
    CONSUMABLE = "소모품"
    # 독립적인 코스트/사거리를 가진 전투 전용 소비형 스킬 슬롯.
    BATTLE_CONSUMABLE = "전투 소모품"
    # 전투 밖에서만 사용 가능. effect는 없으며(항상 None), 자신만을 대상으로
    # 아이템별 전용 로직(app/bot/commands/noncombat.py)으로 처리된다.
    NONCOMBAT_CONSUMABLE = "비전투 소모품"
    # 전투 시 특수 효과를 내는 추가 패시브 스킬. 현재 미구현.
    CHARM = "부적"
    # 소지 자체가 목적인 아이템 — 전투/비전투 어느 쪽으로도 쓸 수 없다.
    ETC = "기타"


class BuffApplyTiming(str, Enum):
    ON_BATTLE_START = "전투 시작 시"
    ON_ROUND_START = "라운드 시작 시"
    ON_ACTION = "행동 시"
    ON_ENEMY_POST_ACTION = "적 후행 시"
    # 시트 트리거는 ON_ENEMY_POST_ACTION과 같은 "적 후행 시"지만,
    # damaged_this_round가 확정된 뒤에 평가돼야 하는 패시브 전용.
    ON_ENEMY_POST_ACTION_RESOLVED = "적 후행 결과 반영 후"
    ON_ROUND_END = "라운드 종료 시"
    # 자발적 이동과 강제 이동(스킬로 밀려나는 등) 모두 발동한다.
    ON_ENEMY_MOVE = "적 이동 시"
    # 같은 진영·같은 열의 누군가(자신 포함)가 대미지를 입으면 발동한다.
    ALLY_DAMAGED = "아군 피격 시"
    # ALLY_DAMAGED와 동일하되 기준이 "같은 열"이 아니라 "사거리 내"다.
    ALLY_IN_RANGE_DAMAGED = "사거리 내 아군 피격 시"
    # 사거리 내·같은 진영의 누군가가 누군가를 공격하면 발동한다.
    ALLY_IN_RANGE_ATTACKED = "사거리 내 아군 공격 시"


class BuffCountDeductCondition(str, Enum):
    ON_ATTACK = "공격 시"
    ON_HIT = "피격 시"


class FateBoostMode(str, Enum):
    """운명간섭("+", 플레이어 표기 "키워드 보정")이 이 스킬에 무엇을 더해주는지.

    "스킬_캐릭터" 시트의 fate_mode 컬럼(enum 시트 FateBoostMode 드롭다운)에서
    온다. 비워 두면 기존 동작 — 대미지가 나오는 스킬은 굴림에
    FATE_INTERVENTION_SKILL_BONUS를 더하고, 대미지가 없는 스킬은 "+"를
    거부한다. 값을 채우면 그 모드가 기존 동작을 대신한다.

    ROLL_BONUS/VALUE_BOOST는 대미지·회복 수치에 걸리므로 계산 시점
    (command_calculator)에, BUFF_*는 부여할 버프 자체를 바꾸므로 전개 시점
    (command_expanders)에, EXTRA_TARGET은 대상 수 검증
    (command_processors)에 반영된다.
    """

    ROLL_BONUS = "굴림 보정"
    VALUE_BOOST = "수치 강화"
    BUFF_VALUE_BOOST = "버프 수치 강화"
    BUFF_STACK_BOOST = "버프 스택 강화"
    EXTRA_TARGET = "대상 추가"


class SkillTargetOverrideType(str, Enum):
    SELF = "자신"
