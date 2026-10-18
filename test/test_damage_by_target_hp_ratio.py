"""남은 체력 비율 비례 대미지: 적용 시점의 대상 체력 비율을 계수에 곱한다."""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.define import SkillValueType
from battle.objects.skill.effects import SkillEffectDamageByTargetHpRatio
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

USER = CharacterId("시전자")
FOE = CharacterId("적군")


def _setup(foe_hp: int, max_hp: int = 100) -> tuple[BattlefieldContext, RoundManager]:
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamageByTargetHpRatio(
                ValueSourceType.STAT_ATK, 100, SkillValueType.PERCENT, None, None
            )
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"스킬_1": skill})
    ctx.add_character(
        get_test_preset(USER.name, atk=40, skill_1_id="스킬_1"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset(FOE.name, max_hp=max_hp, initial_hp=foe_hp),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    return ctx, manager


def _use(ctx, manager, text: str) -> None:
    manager.process_command(parse_character_command(USER, text, ctx))


def test_damage_is_multiplied_by_remaining_hp_ratio():
    ctx, manager = _setup(foe_hp=50)

    _use(ctx, manager, f"[스킬_1/{FOE.name}]")

    assert ctx.characters[FOE].status.curr_hp == 30


def test_full_hp_takes_full_damage():
    ctx, manager = _setup(foe_hp=100)

    _use(ctx, manager, f"[스킬_1/{FOE.name}]")

    assert ctx.characters[FOE].status.curr_hp == 60


def test_second_hit_in_one_command_uses_the_lowered_hp():
    ctx, manager = _setup(foe_hp=100)

    _use(ctx, manager, f"[스킬_1/{FOE.name} - 스킬_1/{FOE.name}]")

    # 100 → 60 → 60 - 40×0.6 = 36
    assert ctx.characters[FOE].status.curr_hp == 36


def test_formula_shows_the_scaled_coefficient():
    ctx, manager = _setup(foe_hp=50)

    _use(ctx, manager, f"[스킬_1/{FOE.name}]")

    displays = [e.roll_display for r in ctx.results for e in r.log_entries]
    assert any("남은 체력 비율 0.50" in (d or "") for d in displays)


def test_ratio_is_floored_to_two_decimals():
    """체력 200/300(0.666…)은 0.66으로 버려 그 값으로 곱한다(40 × 0.66 → 26)."""
    ctx, manager = _setup(foe_hp=200, max_hp=300)

    _use(ctx, manager, f"[스킬_1/{FOE.name}]")

    displays = [e.roll_display for r in ctx.results for e in r.log_entries]
    assert any("남은 체력 비율 0.66" in (d or "") for d in displays)
    assert ctx.characters[FOE].status.curr_hp == 174
