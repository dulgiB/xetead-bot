"""버프 분류(BuffType)가 집계 조건을 실제로 가르는지 검증한다.

해제 불가 마커나 대상 유도([도발]) 같은 효과는 버프·디버프 어느 쪽으로 넣어도
틀린다 — 디버프로 두면 "디버프가 걸린 적에게 주는 대미지 증가" 계열이 탱커의
도발만으로 켜지고, 버프로 두면 "자신에게 버프가 있을 때" 조건이 도발당한
것만으로 충족된다. NEUTRAL은 그 어느 집계에도 잡히지 않게 한다.
"""

import pytest
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.conditions import (
    HolderHasBuffCondition,
    TargetHasDebuffCondition,
)
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.core.battlefield_context import BattlefieldContext
from battle.objects.skill.effects import SkillEffectRemoveDebuffs
from helpers import get_test_preset

HOLDER = CharacterId("A")
OTHER = CharacterId("B")


def _buff(buff_id: str, buff_class_name: str, buff_type: BuffType) -> BuffData:
    # 클래스 이름이 같으면 기본 uid((given_by, applied_to, buff_class_name))가
    # 겹쳐 한 인스턴스로 합쳐진다 — 세 분류를 동시에 들려야 하므로 서로 다른
    # 클래스를 쓴다.
    return BuffData(
        id=buff_id,
        buff_class_name=buff_class_name,
        duration_turn_value=2,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=10,
        condition_=None,
        condition_value=None,
        buff_type=buff_type,
        description="",
    )


@pytest.fixture
def context() -> BattlefieldContext:
    ctx = BattlefieldContext(
        buff_dict={
            "이로움": _buff("이로움", "BuffReceivedDamage", BuffType.BUFF),
            "해로움": _buff("해로움", "BuffGivenDamage", BuffType.DEBUFF),
            "중립": _buff("중립", "BuffAtk", BuffType.NEUTRAL),
        },
        skill_dict={},
    )
    ctx.add_character(get_test_preset("A"), FactionType.ALLY, BattlefieldColumnIndex(0))
    ctx.add_character(
        get_test_preset("B"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return ctx


def _give(ctx, buff_id: str, to: CharacterId) -> None:
    ctx.buff_container.add(BuffAddData(given_by=HOLDER, applied_to=to, buff_id=buff_id))


@pytest.mark.parametrize(
    "buff_id, counts_as_buff, counts_as_debuff",
    [("이로움", True, False), ("해로움", False, True), ("중립", False, False)],
)
def test_conditions_only_count_their_own_type(
    context, buff_id, counts_as_buff, counts_as_debuff
):
    _give(context, buff_id, OTHER)
    assert (
        HolderHasBuffCondition(value=None).is_applied(context, OTHER, None)
        is counts_as_buff
    )
    assert (
        TargetHasDebuffCondition(value=None).is_applied(context, HOLDER, OTHER)
        is counts_as_debuff
    )


def test_debuff_removal_leaves_buffs_and_neutral_markers(context):
    for buff_id in ("이로움", "해로움", "중립"):
        _give(context, buff_id, OTHER)
    effect = SkillEffectRemoveDebuffs(
        value_source=None,
        value=None,
        value_type=None,
        buff_id=None,
        buff_add_timing=None,
    )

    assert effect.get_debuff_clear_targets(context, [OTHER]) == [OTHER]
    effect.expand(context, HOLDER, [OTHER])

    remaining = {b.id for b in context.buff_container.get_buffs_by(OTHER, None)}
    assert remaining == {"이로움", "중립"}
