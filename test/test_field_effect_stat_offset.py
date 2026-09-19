"""필드 효과의 스탯 증감(기믹 1).

버프(BuffedStats)로는 표현할 수 없는 부분이 핵심이다 — BuffedStats는
CommandPartCalculator 안에서만 살기 때문에, 사거리 검증·범위 조건·필드 시트
표시처럼 CombatStats를 직접 읽는 지점에는 반영되지 않는다. 그래서 필드 효과의
스탯 증감은 CombatStats에 직접 얹는다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
    ValueSourceType,
)
from battle.objects.field_effect.models import FieldEffectSource
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import SkillEffectFieldStatOffset
from helpers import get_test_preset

EFFECT_ID = "FieldEffect"


def _stat_offset_effect(
    value_source: ValueSourceType,
    amount: int,
    target_type: PassiveSkillTargetType = PassiveSkillTargetType.FIELD_ALLY_SIDE,
    effect_id: str = EFFECT_ID,
) -> PassiveSkillData:
    return PassiveSkillData(
        id=effect_id,
        # 스탯 증감은 트리거와 무관하게 걸려 있는 동안 유지되므로, 트리거 값은
        # 이 효과의 동작에 영향을 주지 않는다.
        trigger=PassiveSkillTrigger.BATTLE_START,
        target_type=target_type,
        effects=[
            SkillEffectFieldStatOffset(
                value_source=value_source,
                value=amount,
                value_type=None,
                buff_id=None,
                buff_add_timing=None,
            )
        ],
        description="",
    )


def _make_context(*effects: PassiveSkillData) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={},
        skill_dict={},
        passive_skill_dict={effect.id: effect for effect in effects},
    )


def _manager(ctx: BattlefieldContext) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return manager


class TestRangeOffset:
    """사거리는 CombatStats를 직접 읽는 지점이 여럿이라, 증감이 실제 사거리
    검증까지 닿는지가 이 기믹의 진짜 시험대다."""

    def _setup(self, offset: int) -> BattlefieldContext:
        ctx = _make_context(_stat_offset_effect(ValueSourceType.STAT_RANGE, offset))
        ctx.add_character(
            get_test_preset("공격자", attack_range=1),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(2)
        )
        return ctx

    def test_out_of_range_attack_fails_without_effect(self):
        ctx = self._setup(0)
        manager = _manager(ctx)
        manager.to_phase(RoundPhaseType.ALLY_ACTION)

        with pytest.raises(CommandValidationError):
            manager.process_command(
                parse_character_command(CharacterId("공격자"), "[공격/적군]", ctx)
            )

    def test_range_offset_makes_attack_reach(self):
        # 사거리 1 + 2 = 3이면 2열 떨어진 대상에 닿는다.
        ctx = self._setup(2)
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        manager = _manager(ctx)
        manager.to_phase(RoundPhaseType.ALLY_ACTION)

        manager.process_command(
            parse_character_command(CharacterId("공격자"), "[공격/적군]", ctx)
        )

        assert ctx.characters[CharacterId("적군")].status.curr_hp < 100

    def test_offset_is_visible_on_combat_stats(self):
        ctx = self._setup(2)
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        assert (
            ctx.characters[CharacterId("공격자")].status[CombatStatType.RANGE] == 1 + 2
        )

    def test_removing_effect_restores_original_range(self):
        ctx = self._setup(2)
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.remove_field_effect(EFFECT_ID)

        assert ctx.characters[CharacterId("공격자")].status[CombatStatType.RANGE] == 1


class TestScope:
    def test_only_targets_in_scope_are_offset(self):
        ctx = _make_context(
            _stat_offset_effect(
                ValueSourceType.STAT_RANGE, 2, PassiveSkillTargetType.FIELD_ALLY_SIDE
            )
        )
        ctx.add_character(
            get_test_preset("아군", attack_range=3),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", attack_range=3),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        assert ctx.characters[CharacterId("아군")].status[CombatStatType.RANGE] == 5
        assert ctx.characters[CharacterId("적군")].status[CombatStatType.RANGE] == 3

    def test_newcomer_receives_offset(self):
        ctx = _make_context(_stat_offset_effect(ValueSourceType.STAT_RANGE, 2))
        ctx.add_character(
            get_test_preset("아군", attack_range=3),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.add_character(
            get_test_preset("증원", attack_range=3),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )

        assert ctx.characters[CharacterId("증원")].status[CombatStatType.RANGE] == 5

    def test_two_effects_on_same_stat_are_summed(self):
        ctx = _make_context(
            _stat_offset_effect(ValueSourceType.STAT_RANGE, 2, effect_id="FieldEffect"),
            _stat_offset_effect(
                ValueSourceType.STAT_RANGE, -1, effect_id="FieldEffect2"
            ),
        )
        ctx.add_character(
            get_test_preset("아군", attack_range=3),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_field_effect("FieldEffect", FieldEffectSource.ADMIN)
        ctx.add_field_effect("FieldEffect2", FieldEffectSource.ADMIN)

        assert ctx.characters[CharacterId("아군")].status[CombatStatType.RANGE] == 4

        ctx.remove_field_effect("FieldEffect")

        assert ctx.characters[CharacterId("아군")].status[CombatStatType.RANGE] == 2


class TestCostOffset:
    def test_cost_offset_applies_from_next_round_refill(self):
        """코스트는 라운드 시작에 최대치로 회복되므로, 증감은 그 회복을 통해
        반영된다."""
        ctx = _make_context(_stat_offset_effect(ValueSourceType.STAT_COST_PER_TURN, 2))
        ctx.add_character(
            get_test_preset("아군", max_cost=3),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.on_start_round()

        assert ctx.characters[CharacterId("아군")].status.remaining_cost == 5


class TestAtkOffset:
    def test_atk_offset_raises_damage(self):
        ctx = _make_context(_stat_offset_effect(ValueSourceType.STAT_ATK, 50))
        ctx.add_character(
            get_test_preset("공격자", atk=5),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        manager = _manager(ctx)
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("공격자"), "[공격/적군]", ctx)
        )

        # 공격력 5+50 = 55, 주사위 1d6 → 56~61.
        damage = 100 - ctx.characters[CharacterId("적군")].status.curr_hp
        assert 56 <= damage <= 61


class TestUnsupportedStat:
    def test_max_hp_offset_is_skipped(self):
        """최대 체력은 일부러 지원하지 않는다 — 조용히 건너뛰고 스탯은
        그대로여야 한다."""
        ctx = _make_context(_stat_offset_effect(ValueSourceType.STAT_MAX_HP, 50))
        ctx.add_character(
            get_test_preset("아군", max_hp=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        assert ctx.characters[CharacterId("아군")].status[CombatStatType.MAX_HP] == 100
