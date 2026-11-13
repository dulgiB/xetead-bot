"""공격 쪽 버프의 대상별 판정과 같은 클래스 공격력 버프의 공존.

- 광역기는 ON_ATTACK 디스패치가 공격자당 한 번이라, 대상에 따라 갈리는
  조건(거리·이동 여부 등)을 첫 대상 하나로 판정하면 그 결과가 전원에게
  똑같이 붙었다. 대상마다 따로 판정한다.
- 공격력 증가(BuffAtk)는 행(id)이 다르면 같은 부여자가 걸어도 따로 유지된다.
"""

from typing import Optional

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData, BuffUid
from battle.objects.buff.buffs import BuffAtk
from battle.objects.buff.conditions import TargetAtLeastDistanceCondition
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import SkillEffectDamage
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

HOLDER = CharacterId("보유자")
NEAR = CharacterId("가까운 대상")
FAR = CharacterId("먼 대상")
MOVED = CharacterId("이동한 대상")


def _buff(
    buff_id: str,
    class_name: str,
    value: int,
    value_type: ValueType,
    condition: Optional[str] = None,
    condition_value: Optional[int] = None,
) -> BuffData:
    return BuffData(
        id=buff_id,
        buff_class_name=class_name,
        duration_turn_value=3,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=value_type,
        value=value,
        condition_=condition,
        condition_value=condition_value,
        buff_type=BuffType.BUFF,
        description="",
    )


BUFFS = {
    "거리_공격력": _buff(
        "거리_공격력",
        "BuffAtk",
        5,
        ValueType.INTEGER,
        "TargetAtLeastDistanceCondition",
        2,
    ),
    "정지_공격력": _buff(
        "정지_공격력",
        "BuffAtk",
        5,
        ValueType.INTEGER,
        "TargetDidNotMoveThisTurnCondition",
    ),
    "거리_대미지": _buff(
        "거리_대미지",
        "BuffGivenDamage",
        100,
        ValueType.PERCENT,
        "TargetAtLeastDistanceCondition",
        2,
    ),
}

# 공격력 그대로(100%)를 대미지로 — 굴림이 없어 수치를 바로 비교할 수 있다.
AREA = SkillData(
    id="광역_1",
    target_rule="SkillTargetRuleColumn",
    target_count=3,
    cost=0,
    effects=[
        SkillEffectDamage(ValueSourceType.STAT_ATK, 100, ValueType.PERCENT, None, None)
    ],
    description="",
)


def _setup(passive: Optional[PassiveSkillData] = None):
    ctx = BattlefieldContext(
        buff_dict=dict(BUFFS),
        skill_dict={AREA.id: AREA},
        passive_skill_dict={"PassiveSkill": passive} if passive else {},
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    ctx.add_character(
        get_test_preset(
            HOLDER.name,
            atk=5,
            attack_range=6,
            skill_1_id=AREA.id,
            passive_skill_id="PassiveSkill" if passive else None,
        ),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    for name, column in ((NEAR, 0), (FAR, 3), (MOVED, 4)):
        ctx.add_character(
            get_test_preset(name.name),
            FactionType.ENEMY,
            BattlefieldColumnIndex(column),
        )
    return ctx, manager


def _give(ctx: BattlefieldContext, *buff_ids: str) -> None:
    for buff_id in buff_ids:
        ctx.buff_container.add(
            BuffAddData(given_by=HOLDER, applied_to=HOLDER, buff_id=buff_id)
        )


def _taken(ctx: BattlefieldContext, char_id: CharacterId) -> int:
    return 100 - ctx.characters[char_id].status.curr_hp


def _hit_all(ctx: BattlefieldContext, manager: RoundManager) -> None:
    manager.process_command(parse_character_command(HOLDER, "[광역_1/1/4/5]", ctx))


def test_two_atk_buffs_from_same_giver_coexist():
    ctx, _ = _setup()
    _give(ctx, "거리_공격력", "정지_공격력")

    ids = {b.id for b in ctx.buff_container.get_buffs_by(HOLDER, None)}
    assert ids == {"거리_공격력", "정지_공격력"}


def test_reapplying_same_atk_buff_still_refreshes():
    ctx, _ = _setup()
    _give(ctx, "거리_공격력", "거리_공격력")

    assert len(ctx.buff_container.get_buffs_by(HOLDER, None)) == 1


def test_area_atk_bonus_is_judged_per_target():
    ctx, manager = _setup()
    _give(ctx, "거리_공격력")

    _hit_all(ctx, manager)

    # 같은 열(거리 0)은 공격력 그대로, 거리 2 이상은 +5.
    assert _taken(ctx, NEAR) == 5
    assert _taken(ctx, FAR) == 10
    assert _taken(ctx, MOVED) == 10


def test_area_given_damage_is_judged_per_target():
    ctx, manager = _setup()
    _give(ctx, "거리_대미지")

    _hit_all(ctx, manager)

    assert _taken(ctx, NEAR) == 5
    assert _taken(ctx, FAR) == 10


def test_stacked_atk_buffs_each_judged_per_target():
    ctx, manager = _setup()
    _give(ctx, "거리_공격력", "정지_공격력")
    ctx.moved_this_round.add(MOVED)

    _hit_all(ctx, manager)

    assert _taken(ctx, NEAR) == 10  # 정지만
    assert _taken(ctx, FAR) == 15  # 거리 + 정지
    assert _taken(ctx, MOVED) == 10  # 거리만


def test_passive_buff_mod_is_judged_per_target():
    template = BuffAtk._create_bare(
        id_="PassiveBuff",
        uid=BuffUid(HOLDER, HOLDER, "BuffAtk"),
        given_by=HOLDER,
        applied_to=HOLDER,
        value=5,
        value_type=ValueType.INTEGER,
        condition=TargetAtLeastDistanceCondition(value=2),
    )
    passive = PassiveSkillData(
        id="PassiveSkill",
        trigger=PassiveSkillTrigger.ON_ACTION,
        target_type=PassiveSkillTargetType.SELF,
        effects=[],
        description="",
        buff_mod_event=template.create_event(),
    )
    ctx, manager = _setup(passive)

    _hit_all(ctx, manager)

    assert _taken(ctx, NEAR) == 5
    assert _taken(ctx, FAR) == 10


def test_single_target_attack_unchanged():
    ctx, manager = _setup()
    _give(ctx, "거리_공격력")

    manager.process_command(parse_character_command(HOLDER, "[광역_1/1]", ctx))

    assert _taken(ctx, NEAR) == 5
