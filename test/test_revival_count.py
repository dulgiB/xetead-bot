"""부활 횟수(revival_count)에 따른 상시 수치 효과 테스트.

부활 횟수는 GM이 "캐릭터" 시트에서 직접 관리하는 값이고, 봇은 배치 시점에
읽어 아래 세 가지에만 반영한다 — 받는 대미지 증가, 턴당 코스트, 이동 코스트.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_processors import process_ally_command
from battle.core.commands.parser import parse_character_command
from battle.objects.define import (
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.extensions import get_total_cost
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectDamage
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

_ATTACKER = CharacterId("Catastrophe")
_TARGET = CharacterId("Adversary")

_FIXED_DAMAGE = 30


def _damage_skill() -> SkillData:
    """받는 대미지 배율만 검증하도록 굴림 없는 고정 대미지 스킬을 쓴다."""
    return SkillData(
        id="Cost2Skill",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectDamage(
                ValueSourceType.FIXED, _FIXED_DAMAGE, ValueType.INTEGER, None, None
            )
        ],
        description="",
    )


def _make_context(
    *,
    attacker_revival: int = 0,
    target_revival: int = 0,
    attacker_max_cost: int = 3,
) -> BattlefieldContext:
    context = BattlefieldContext(
        buff_dict={}, skill_dict={"Cost2Skill": _damage_skill()}
    )
    context.add_character(
        get_test_preset(
            _ATTACKER.name,
            max_cost=attacker_max_cost,
            revival_count=attacker_revival,
            skill_1_id="Cost2Skill",
        ),
        FactionType.ALLY,
        BattlefieldColumnIndex(3),
    )
    context.add_character(
        get_test_preset(_TARGET.name, revival_count=target_revival),
        FactionType.ENEMY,
        BattlefieldColumnIndex(3),
    )
    return context


def _run(context: BattlefieldContext, text: str):
    command = parse_character_command(_ATTACKER, text, context)
    assert command is not None
    return process_ally_command(context, command)


# ── 받는 대미지 페널티 ───────────────────────────────────────────────────────


def test_revival_increases_received_damage():
    """부활 횟수 × 10%만큼 받는 대미지가 늘어난다."""
    plain = _make_context(target_revival=0)
    _run(plain, f"[Cost2Skill/{_TARGET.name}]")
    plain_damage = 100 - plain.characters[_TARGET].status.curr_hp

    revived = _make_context(target_revival=2)
    _run(revived, f"[Cost2Skill/{_TARGET.name}]")
    revived_damage = 100 - revived.characters[_TARGET].status.curr_hp

    # 고정 대미지에도 적용되어야 한다 (마법 저항과 같은 게임 메커니즘).
    assert plain_damage == _FIXED_DAMAGE
    assert revived_damage == 36  # 30 × (1 + 0.2)


def test_revival_penalty_absent_without_revival():
    """부활한 적이 없으면 페널티 modifier 자체가 붙지 않는다."""
    context = _make_context(target_revival=0)
    assert context.characters[_TARGET].status.revival_penalty is None


# ── 코스트 보정 (4회 이상) ───────────────────────────────────────────────────


def test_revival_4_increases_cost_per_turn():
    """부활 4회 이상이면 턴당 코스트가 +1 된다."""
    context = _make_context(attacker_revival=4, attacker_max_cost=3)
    status = context.characters[_ATTACKER].status
    assert status[CombatStatType.COST_PER_TURN] == 4
    assert status.remaining_cost == 4


def test_cost_per_turn_unchanged_below_threshold():
    """부활 3회까지는 턴당 코스트가 그대로다."""
    context = _make_context(attacker_revival=3, attacker_max_cost=3)
    assert context.characters[_ATTACKER].status[CombatStatType.COST_PER_TURN] == 3


def test_revival_4_increases_move_cost_per_move_part():
    """부활 4회 이상이면 이동 코스트가 이동 파트마다 +1 된다."""
    context = _make_context(attacker_revival=4)
    command = parse_character_command(_ATTACKER, "[이동/5 - 이동/6]", context)
    assert command is not None
    # 4열 → 5열(1) + 5열 → 6열(1) = 2, 이동 파트가 2개이므로 +2
    assert get_total_cost(command.parts, _ATTACKER, context) == 4


def test_move_cost_unchanged_below_threshold():
    """부활 3회까지는 이동 코스트가 그대로다."""
    context = _make_context(attacker_revival=3)
    command = parse_character_command(_ATTACKER, "[이동/5 - 이동/6]", context)
    assert command is not None
    assert get_total_cost(command.parts, _ATTACKER, context) == 2
