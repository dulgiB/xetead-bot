"""대련/상시전투에서 1턴짜리 효과가 순서 추첨 때문에 무효가 되지 않는지 검증한다.

이 구조는 양 팀이 한 라운드 안에서 각자 한 번씩 행동하고, 지속시간은 라운드
종료에 차감된다. 그래서 라운드의 마지막 차례에 상대에게 건 1턴 효과(도발·약화
등)는 상대가 그 상태로 행동할 기회를 한 번도 얻지 못한 채 사라졌다 — 코스트를
쓴 행동이 통째로 무효가 되는데, 순서는 플레이어가 고를 수 없다.

해결은 "그 페이즈 중에 걸린 효과는 이번 라운드 종료 차감에서 건너뛴다"는
유예다. 선공에 걸든 후공에 걸든 상대의 행동 기회가 정확히 한 번 보장되고,
그 다음 라운드 종료에는 정상적으로 사라진다.
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


def _one_turn_debuff() -> BuffData:
    return BuffData.from_dict(
        {
            "id": DEBUFF_ID,
            "buff_name": "BuffGivenDamage",
            "duration_turn_value": 1,
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


def _practice_context() -> PracticeBattlefieldContext:
    ctx = PracticeBattlefieldContext(
        buff_dict={DEBUFF_ID: _one_turn_debuff()}, skill_dict={}
    )
    ctx.add_character(
        get_test_preset(CASTER.name), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset(FOE.name), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )
    return ctx


def _cast_debuff_on_foe(ctx: PracticeBattlefieldContext) -> None:
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


def test_debuff_cast_in_the_last_phase_survives_into_the_next_round():
    """후공(마지막 차례)에 건 1턴 디버프는 상대가 행동할 다음 라운드까지 남는다."""
    ctx = _practice_context()
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


def test_debuff_cast_in_the_first_phase_still_expires_with_the_round():
    """선공에 걸면 같은 라운드 후공에 이미 값을 다 했으므로 기존대로 사라진다."""
    ctx = _practice_context()
    manager = PracticeRoundManager(ctx)

    _start_round(manager, caster_side_first=True)
    _cast_debuff_on_foe(ctx)
    manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
    assert _has_debuff(ctx)  # 상대가 이 상태로 행동한다
    manager.end_round()

    assert not _has_debuff(ctx)


def test_effect_applied_before_the_last_phase_is_not_granted_the_grace():
    """라운드 시작 훅이 건 버프("적 후행 시" 패시브의 방어 버프 등)는 유예
    대상이 아니다 — 그 라운드를 지키라고 걸린 것이므로 라운드와 함께 끝나야
    한다. 유예 기준을 페이즈 시작 시점으로 잡는 이유다(같은 훅이 실제
    패시브로 도는 경로는 test_practice_enemy_post_action_timing.py)."""
    ctx = _practice_context()
    manager = PracticeRoundManager(ctx)

    # 라운드 시작 훅과 같은 순서(페이즈 진입 전)로 건다.
    _cast_debuff_on_foe(ctx)
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
    manager.end_round()

    assert not _has_debuff(ctx)


def test_main_battle_duration_is_unchanged():
    """본 전투는 유예를 쓰지 않는다 — 아군 행동 뒤에 적 후행 정산이 오도록
    페이즈가 고정돼 있어 마지막 차례에 걸린 효과가 사라지는 문제가 없다."""
    ctx = BattlefieldContext(buff_dict={DEBUFF_ID: _one_turn_debuff()}, skill_dict={})
    ctx.add_character(
        get_test_preset(CASTER.name), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset(FOE.name), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.on_start_round()
    ctx.buff_container.add(
        BuffAddData(given_by=CASTER, applied_to=FOE, buff_id=DEBUFF_ID)
    )

    ctx.on_finish_round()

    assert not _has_debuff(ctx)
