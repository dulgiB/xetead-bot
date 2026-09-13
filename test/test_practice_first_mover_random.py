"""대련/상시전투의 선공/후공은 매 라운드 다시 뽑는다.

대련의 밸런스는 PvE 기준으로 짜인 캐릭터를 그대로 맞붙이는 것이라, 순서를
고정하면 불리한 캐릭터가 매번 같은 방식으로 진다. 매 라운드 추첨은 "선공을
잡으면 상대가 행동하기 전에 끝낼 수도 있다"는 역전 여지를 남기는 밸런스
장치다.

한때 이 추첨을 교대로 바꾼 적이 있는데, 그 이유는 후공 페이즈에 건 1턴
효과가 상대의 행동 기회 없이 사라지는 문제였다. 그건 이제 지속시간 차감
쪽에서 해결하므로(test_practice_turn_duration.py) 순서는 추첨으로 되돌린다.
"""

import random

from battle.objects.define import BattlefieldColumnIndex
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager
from helpers import get_test_preset


def _manager() -> PracticeRoundManager:
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    return PracticeRoundManager(ctx)


def _play_round(manager: PracticeRoundManager) -> SideType:
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    first_mover = manager.first_mover
    assert first_mover is not None
    manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
    manager.end_round()
    return first_mover


def test_first_mover_is_redrawn_every_round():
    """교대였다면 나올 수 없는 "같은 팀 2연속 선공"이 실제로 나와야 한다."""
    random.seed(20260913)
    manager = _manager()

    movers = [_play_round(manager) for _ in range(30)]

    assert any(a == b for a, b in zip(movers, movers[1:]))
    # 한쪽으로 쏠린 추첨이 아니어야 한다.
    assert 5 < movers.count(SideType.SIDE_1) < 25


def test_second_mover_is_always_the_other_side():
    manager = _manager()
    for _ in range(5):
        manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
        assert manager.first_mover is not None
        assert manager.second_mover == manager.first_mover.opposite
        manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
        manager.end_round()


def test_restored_session_redraws_on_the_next_round():
    """복원 직후의 라운드도 추첨 대상이다 — 복원값은 진행 중이던 그 라운드를
    이어가기 위한 것이지, 이후 순서를 고정하는 값이 아니다."""
    manager = _manager()
    manager.set_phase_for_restore(
        PracticeRoundPhase.SECOND_MOVER_ACTION, SideType.SIDE_1, SideType.SIDE_2
    )

    assert manager.first_mover == SideType.SIDE_1
    manager.end_round()
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)

    assert manager.first_mover in (SideType.SIDE_1, SideType.SIDE_2)
    assert manager.second_mover == manager.first_mover.opposite
