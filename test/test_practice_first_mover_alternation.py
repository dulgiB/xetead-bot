"""대련의 선공/후공은 첫 라운드에만 무작위로 정하고 이후로는 교대한다.

매 라운드 다시 뽑으면 1턴짜리 버프/디버프의 가치가 추첨 결과에 따라 요동친다.
지속시간은 라운드 종료에 차감되므로, 후공 페이즈에 건 1턴 효과는 상대가 행동할
기회 없이 그대로 사라진다 — 한 팀이 내리 후공을 뽑으면 그 팀의 1턴 효과만
계속 값을 못 하게 된다.
"""

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


def test_first_mover_alternates_after_the_opening_draw():
    manager = _manager()

    movers = []
    for _ in range(4):
        manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
        movers.append(manager.first_mover)
        manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
        manager.end_round()

    assert [m.opposite for m in movers[:-1]] == movers[1:]
    # 4라운드면 양 팀이 정확히 두 번씩 선공을 잡는다.
    assert movers.count(SideType.SIDE_1) == movers.count(SideType.SIDE_2) == 2


def test_second_mover_is_always_the_other_side():
    manager = _manager()
    for _ in range(3):
        manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
        assert manager.second_mover == manager.first_mover.opposite
        manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
        manager.end_round()


def test_restored_first_mover_alternates_from_the_restored_value():
    """재기동 복원 후에도 교대가 이어져야 한다 — 복원 시점에 다시 추첨하면
    크래시 전후로 같은 팀이 두 번 연속 선공을 잡을 수 있다."""
    manager = _manager()
    manager.set_phase_for_restore(
        PracticeRoundPhase.SECOND_MOVER_ACTION, SideType.SIDE_1, SideType.SIDE_2
    )

    manager.end_round()
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)

    assert manager.first_mover == SideType.SIDE_2
