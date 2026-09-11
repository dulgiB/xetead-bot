from enum import Enum


class RoundPhaseType(str, Enum):
    # 이동/버프만 선적용하고 대미지는 ENEMY_POST_ACTION으로 미룬다.
    ENEMY_PRE_ACTION = "적 행동 선언"

    ALLY_ACTION = "아군 행동"

    ENEMY_POST_ACTION = "적 공격 정산"

    # 버프 턴수 차감·제거 후 다음 라운드 시작 대기.
    BUFF_UPDATE_AND_NEXT_ROUND_STANDBY = "라운드 종료"
