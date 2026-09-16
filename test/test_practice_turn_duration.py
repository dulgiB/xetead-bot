"""대련/결투/상시전투의 지속시간 차감이 본 전투와 같은 규칙인지 검증한다.

이 구조는 양 팀이 한 라운드 안에서 각자 한 번씩 행동하고, 지속시간은 본 전투와
똑같이 라운드 종료에 차감된다 — 부여가 선공 차례였는지 후공 차례였는지는 보지
않는다. 대련은 본 전투 규칙에 익숙해지는 자리이기도 해서, 같은 데이터가 모드마다
다르게 보이지 않는 편을 택했다.

그 결과 라운드의 마지막 차례에 상대에게 건 1턴짜리 효과는 상대가 그 상태로
행동할 기회를 얻지 못한 채 사라진다. 상대의 행동에 걸리기를 기대하는 효과는
데이터 쪽에서 2턴 이상으로 적어 해결한다(아래 2턴 케이스).
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager
from helpers import get_test_preset

DEBUFF_ID = "약화"
CASTER = CharacterId("Caster")
FOE = CharacterId("Foe")


def _debuff(duration_turn_value: int) -> BuffData:
    return BuffData.from_dict(
        {
            "id": DEBUFF_ID,
            "buff_name": "BuffGivenDamage",
            "duration_turn_value": duration_turn_value,
            "duration_count_value": "",
            "duration_count_deduct_condition": "",
            "value_0": -50,
            "value_type_0": "퍼센트",
            "value_1": "",
            "value_type_1": "",
            "condition": "",
            "condition_value": "",
            "type": "디버프",
            "max_stack": "",
            "reference_buff_id": "",
            "description": "",
        }
    )


def _practice_context(duration_turn_value: int = 1) -> PracticeBattlefieldContext:
    ctx = PracticeBattlefieldContext(
        buff_dict={DEBUFF_ID: _debuff(duration_turn_value)}, skill_dict={}
    )
    ctx.add_character(
        get_test_preset(CASTER.name), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset(FOE.name), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )
    return ctx


def _cast_debuff_on_foe(ctx: BattlefieldContext) -> None:
    ctx.buff_container.add(
        BuffAddData(given_by=CASTER, applied_to=FOE, buff_id=DEBUFF_ID)
    )


def _has_debuff(ctx: BattlefieldContext) -> bool:
    return ctx.buff_container.get_buff(FOE, DEBUFF_ID) is not None


def _start_round(manager: PracticeRoundManager, caster_side_first: bool) -> None:
    """선공을 고정한 채 라운드를 연다(순서는 매 라운드 추첨이므로 직접 지정)."""
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    manager.set_phase_for_restore(
        PracticeRoundPhase.FIRST_MOVER_ACTION,
        SideType.SIDE_1 if caster_side_first else SideType.SIDE_2,
        SideType.SIDE_2 if caster_side_first else SideType.SIDE_1,
    )


def test_one_turn_debuff_expires_with_the_round_whichever_phase_cast_it():
    """1턴 효과는 선공에 걸든 후공에 걸든 그 라운드 종료에 사라진다 —
    부여 차례에 따라 지속시간이 갈리지 않는다."""
    for caster_side_first in (True, False):
        ctx = _practice_context()
        manager = PracticeRoundManager(ctx)

        _start_round(manager, caster_side_first=caster_side_first)
        if caster_side_first:
            _cast_debuff_on_foe(ctx)
            manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
        else:
            manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
            _cast_debuff_on_foe(ctx)
        manager.end_round()

        assert not _has_debuff(ctx)


def test_two_turn_debuff_reaches_the_next_round_from_the_last_phase():
    """상대의 행동에 걸려야 하는 효과는 2턴으로 적어 해결한다 — 라운드의 마지막
    차례에 걸어도 상대가 행동할 다음 라운드까지 남는다."""
    ctx = _practice_context(duration_turn_value=2)
    manager = PracticeRoundManager(ctx)

    _start_round(manager, caster_side_first=False)  # 상대가 먼저 행동
    manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
    _cast_debuff_on_foe(ctx)  # 시전자의 차례 = 이 라운드의 마지막 차례
    manager.end_round()

    assert _has_debuff(ctx)

    # 다음 라운드에 상대가 이 상태로 행동하고, 그 라운드 종료에는 사라진다.
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    assert _has_debuff(ctx)
    manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
    manager.end_round()
    assert not _has_debuff(ctx)


def test_main_battle_duration_matches():
    """본 전투도 같다 — 같은 데이터가 모드에 따라 다르게 동작하지 않는다."""
    ctx = BattlefieldContext(buff_dict={DEBUFF_ID: _debuff(1)}, skill_dict={})
    ctx.add_character(
        get_test_preset(CASTER.name), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset(FOE.name), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.on_start_round()
    _cast_debuff_on_foe(ctx)

    ctx.on_finish_round()

    assert not _has_debuff(ctx)
