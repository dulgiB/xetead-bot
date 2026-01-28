from enum import Enum


class RoundPhaseType(Enum):
    # 적군 행동 선언, 이동/버프 선적용
    ENEMY_PRE_ACTION = 1

    # 아군 행동
    ALLY_ACTION = 2

    # 적군 공격 정산
    ENEMY_POST_ACTION = 3

    # 버프/디버프 턴수 차감 및 제거, 다음 라운드 시작 대기
    BUFF_UPDATE_AND_NEXT_ROUND_STANDBY = 4
