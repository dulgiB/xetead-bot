"""대련은 양 팀이 대등한 PvP인데, 내부적으로 SIDE_1 → 아군 / SIDE_2 → 적군에
매핑돼 있어서 진영별로 다르게 동작하는 규칙이 그대로 "2팀에만 적용되는"
비대칭이 된다. 승패를 체력 비율로 가르는 구조라 그 비대칭이 곧 판정 왜곡이다.

상시전투는 실제로 아군 vs 적군 구도이므로 기존 규칙을 그대로 유지해야 한다 —
두 모드를 가르는 것이 PracticeBattlefieldContext.is_duel이다.
"""

from battle.objects.define import BattlefieldColumnIndex
from battle.objects.models import CharacterId
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager
from bot.practice_state import PracticeBattleState
from helpers import get_test_preset


def _context(*, is_duel: bool) -> PracticeBattlefieldContext:
    return PracticeBattlefieldContext(buff_dict={}, skill_dict={}, is_duel=is_duel)


def _place(ctx, name: str, side: SideType, column: int = 0, **preset_kwargs) -> None:
    ctx.add_character(
        get_test_preset(name, **preset_kwargs), side, BattlefieldColumnIndex(column)
    )


def _finish_a_round(ctx) -> None:
    manager = PracticeRoundManager(ctx)
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    manager.end_round()


def test_duel_does_not_auto_remove_either_side_on_zero_hp():
    """대련에서는 어느 팀의 0 체력 캐릭터도 자동으로 필드에서 빠지지 않는다."""
    ctx = _context(is_duel=True)
    _place(ctx, "A", SideType.SIDE_1)
    _place(ctx, "A2", SideType.SIDE_1)
    _place(ctx, "B", SideType.SIDE_2)
    _place(ctx, "B2", SideType.SIDE_2)
    ctx.characters[CharacterId("A")].status.curr_hp = 0
    ctx.characters[CharacterId("B")].status.curr_hp = 0

    _finish_a_round(ctx)

    assert CharacterId("A") in ctx.characters
    assert CharacterId("B") in ctx.characters


def test_investigation_still_auto_removes_defeated_enemies_only():
    """상시전투는 본 전투와 같은 규칙 — 0 체력 적군(SIDE_2)만 필드에서 빠지고
    아군은 admin이 직접 처리할 때까지 남는다."""
    ctx = _context(is_duel=False)
    _place(ctx, "아군A", SideType.SIDE_1)
    _place(ctx, "아군B", SideType.SIDE_1)
    _place(ctx, "적군A", SideType.SIDE_2)
    _place(ctx, "적군B", SideType.SIDE_2)
    ctx.characters[CharacterId("아군A")].status.curr_hp = 0
    ctx.characters[CharacterId("적군A")].status.curr_hp = 0

    _finish_a_round(ctx)

    assert CharacterId("아군A") in ctx.characters
    assert CharacterId("적군A") not in ctx.characters


def test_duel_winner_is_not_decided_by_who_got_removed_from_the_field():
    """양 팀이 똑같이 한 명씩 잃고 생존자가 둘 다 만피면 무승부여야 한다.

    전사자가 필드에서 빠지면 체력 비율의 분자·분모에서 함께 사라져, 잃은
    쪽이 오히려 100%가 되는 역전이 일어났다.
    """
    ctx = _context(is_duel=True)
    for name, side in (
        ("A", SideType.SIDE_1),
        ("A2", SideType.SIDE_1),
        ("B", SideType.SIDE_2),
        ("B2", SideType.SIDE_2),
    ):
        _place(ctx, name, side)

    ps = PracticeBattleState(context=ctx, manager=PracticeRoundManager(ctx))
    ps.snapshot_initial_max_hp()

    ctx.characters[CharacterId("A")].status.curr_hp = 0
    ctx.characters[CharacterId("B")].status.curr_hp = 0
    _finish_a_round(ctx)

    assert ps.winner() is None


def test_max_hp_denominator_survives_a_participant_leaving_the_field():
    """자진 기권([탈락])으로 필드에서 빠져도 그 캐릭터의 최대 체력은 분모에
    남아야 한다 — 아니면 기권이 곧 비율 상승이 된다."""
    ctx = _context(is_duel=True)
    _place(ctx, "A", SideType.SIDE_1)
    _place(ctx, "A2", SideType.SIDE_1)
    _place(ctx, "B", SideType.SIDE_2)

    ps = PracticeBattleState(context=ctx, manager=PracticeRoundManager(ctx))
    ps.snapshot_initial_max_hp()
    before = ps.total_max_hp_by_side(SideType.SIDE_1)

    ctx.remove_character(CharacterId("A"))

    assert ps.total_max_hp_by_side(SideType.SIDE_1) == before


def test_companion_hp_does_not_count_toward_the_team_score():
    """동료(소환수)는 플레이어가 조작하는 참가자가 아니므로 승패용 체력
    합계에서 빠진다 — 전투 도중 소환·재소환되면서 팀의 체력 총량 자체를
    바꾸기 때문에, 분자에만 더하면 비율이 100%를 넘는다."""
    ctx = _context(is_duel=True)
    _place(ctx, "A", SideType.SIDE_1, max_hp=100)
    _place(ctx, "B", SideType.SIDE_2, max_hp=100)

    ps = PracticeBattleState(context=ctx, manager=PracticeRoundManager(ctx))
    ps.snapshot_initial_max_hp()
    before_hp = ps.total_hp_by_side(SideType.SIDE_1)
    before_max = ps.total_max_hp_by_side(SideType.SIDE_1)

    ctx._spawn_companion_character(
        ctx.characters[CharacterId("A")], CharacterId("P"), 20
    )

    assert ps.total_hp_by_side(SideType.SIDE_1) == before_hp
    assert ps.total_max_hp_by_side(SideType.SIDE_1) == before_max
