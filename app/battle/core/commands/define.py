from enum import Enum


class RoundPhaseType(str, Enum):
    # 적군 행동 선언, 이동/버프 선적용
    ENEMY_PRE_ACTION = "적 행동 선언"

    # 아군 행동
    ALLY_ACTION = "아군 행동"

    # 적군 공격 정산
    ENEMY_POST_ACTION = "적 공격 정산"

    # 버프/디버프 턴수 차감 및 제거, 다음 라운드 시작 대기
    BUFF_UPDATE_AND_NEXT_ROUND_STANDBY = "라운드 종료"
