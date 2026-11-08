"""필드 효과의 패시브 무효화(SkillEffectSuppressPassives).

`필드 적군 진영`으로 걸면 적군의 패시브만 꺼지고 아군 패시브는 그대로다.
패시브는 경로가 여럿(버프_패시브 모디파이어, 스킬 효과, 라운드 트리거, 도발
무시 표시)이라, 각 경로가 빠짐없이 꺼지는지와 걷으면 다시 켜지는지가 핵심이다.
"""

from typing import Optional

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData, BuffBase, BuffUid
from battle.objects.buff.buffs import (
    BuffAtk,
    BuffIgnoreTaunt,
    BuffMaxAttackRoll,
    BuffStripBuffsOnHit,
)
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueType,
)
from battle.objects.field_effect.models import FieldEffectSource
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectSuppressPassives,
)
from bot.field_sheet_renderer import _format_buff_cell
from helpers import get_test_preset

FIELD_EFFECT_ID = "FieldEffect"
PASSIVE_ID = "PassiveSkill"
SELF_BUFF_ID = "SelfBuff"

ENEMY = CharacterId("적군")
ALLY = CharacterId("아군")
TAUNTER = CharacterId("도발자")


def _suppress_field_effect(
    target_type: PassiveSkillTargetType = PassiveSkillTargetType.FIELD_ENEMY_SIDE,
) -> PassiveSkillData:
    return PassiveSkillData(
        id=FIELD_EFFECT_ID,
        trigger=PassiveSkillTrigger.BATTLE_START,
        target_type=target_type,
        effects=[SkillEffectSuppressPassives(None, None, None, None, None)],
        description="패시브 무효화",
    )


def _buff_mod_passive(
    buff_class: type[BuffBase],
    holder: CharacterId,
    *,
    value: int = 0,
    value_type: Optional[ValueType] = None,
) -> PassiveSkillData:
    template = buff_class._create_bare(
        id_="PassiveBuff",
        uid=BuffUid(holder, holder, buff_class.__name__),
        given_by=holder,
        applied_to=holder,
        value=value,
        value_type=value_type,
    )
    return PassiveSkillData(
        id=PASSIVE_ID,
        trigger=PassiveSkillTrigger.ON_ACTION,
        target_type=PassiveSkillTargetType.SELF,
        effects=[],
        description="",
        buff_mod_event=template.create_event(),
    )


def _round_start_self_buff_passive() -> PassiveSkillData:
    return PassiveSkillData(
        id=PASSIVE_ID,
        trigger=PassiveSkillTrigger.ROUND_START,
        target_type=PassiveSkillTargetType.SELF,
        effects=[SkillEffectAddBuff(None, None, None, SELF_BUFF_ID, None)],
        description="",
    )


def _buff_data(buff_id: str, buff_class_name: str, buff_type: BuffType) -> BuffData:
    return BuffData(
        id=buff_id,
        buff_class_name=buff_class_name,
        duration_turn_value=3,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=0,
        condition_=None,
        condition_value=None,
        buff_type=buff_type,
        description="",
    )


def _context(
    passive: PassiveSkillData,
    field_effect: Optional[PassiveSkillData] = None,
    buff_dict: Optional[dict] = None,
) -> BattlefieldContext:
    field_effect = field_effect or _suppress_field_effect()
    return BattlefieldContext(
        buff_dict=buff_dict or {},
        skill_dict={},
        passive_skill_dict={PASSIVE_ID: passive, FIELD_EFFECT_ID: field_effect},
    )


def _manager(ctx: BattlefieldContext) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return manager


def _add(ctx, name, faction, column, **kwargs):
    ctx.add_character(
        get_test_preset(name, **kwargs), faction, BattlefieldColumnIndex(column)
    )


def _damage_taken(ctx: BattlefieldContext, char_id: CharacterId) -> int:
    return 100 - ctx.characters[char_id].status.curr_hp


def _suppress(ctx: BattlefieldContext, turns: Optional[int] = None) -> None:
    assert (
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN, turns=turns)
        is not None
    )


def _enemy_attacks_ally(ctx: BattlefieldContext, manager: RoundManager) -> None:
    manager.process_command(parse_character_command(ENEMY, "[공격/아군]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)


class TestBuffModPassive:
    """버프_패시브 모디파이어 경로(ON_ACTION)."""

    def _setup(self):
        ctx = _context(
            _buff_mod_passive(BuffAtk, ENEMY, value=5, value_type=ValueType.INTEGER)
        )
        manager = _manager(ctx)
        _add(ctx, "적군", FactionType.ENEMY, 0, passive_skill_id=PASSIVE_ID)
        _add(ctx, "아군", FactionType.ALLY, 0)
        return ctx, manager

    def test_enemy_atk_passive_is_off_while_active(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup()
        _suppress(ctx)
        _enemy_attacks_ally(ctx, manager)
        assert _damage_taken(ctx, ALLY) == 5 + 3

    def test_passive_works_again_after_removal(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup()
        _suppress(ctx)
        ctx.remove_field_effect(FIELD_EFFECT_ID)
        _enemy_attacks_ally(ctx, manager)
        assert _damage_taken(ctx, ALLY) == 5 + 5 + 3

    def test_temporary_effect_expires_and_restores(self):
        ctx, _ = self._setup()
        _suppress(ctx, turns=1)
        assert ctx.characters[ENEMY].status.passives_suppressed
        ctx.field_effects.tick_turns()
        assert not ctx.characters[ENEMY].status.passives_suppressed


class TestAllyPassiveUntouched:
    def test_ally_atk_passive_still_works(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx = _context(
            _buff_mod_passive(BuffAtk, ALLY, value=5, value_type=ValueType.INTEGER)
        )
        manager = _manager(ctx)
        _add(ctx, "아군", FactionType.ALLY, 0, passive_skill_id=PASSIVE_ID)
        _add(ctx, "적군", FactionType.ENEMY, 0)
        _suppress(ctx)
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(parse_character_command(ALLY, "[공격/적군]", ctx))
        assert not ctx.characters[ALLY].status.passives_suppressed
        assert _damage_taken(ctx, ENEMY) == 5 + 5 + 3


class TestNewcomer:
    def test_enemy_joining_mid_battle_is_suppressed(self, monkeypatch):
        """소환·도중 참전한 에너미도 즉시 무효화된다."""
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx = _context(
            _buff_mod_passive(BuffAtk, ENEMY, value=5, value_type=ValueType.INTEGER)
        )
        manager = _manager(ctx)
        _add(ctx, "아군", FactionType.ALLY, 0)
        _suppress(ctx)
        _add(ctx, "적군", FactionType.ENEMY, 0, passive_skill_id=PASSIVE_ID)
        _enemy_attacks_ally(ctx, manager)
        assert _damage_taken(ctx, ALLY) == 5 + 3


class TestIgnoreTauntPassive:
    """도발 무시는 이벤트 판정을 거치지 않고 버프에서 바로 읽힌다."""

    def test_taunt_redirects_again(self):
        ctx = _context(
            _buff_mod_passive(BuffIgnoreTaunt, ENEMY),
            buff_dict={"도발": _buff_data("도발", "BuffTaunt", BuffType.NEUTRAL)},
        )
        manager = _manager(ctx)
        _add(ctx, "적군", FactionType.ENEMY, 0, passive_skill_id=PASSIVE_ID)
        _add(ctx, "아군", FactionType.ALLY, 0)
        _add(ctx, "도발자", FactionType.ALLY, 0)
        ctx.buff_container.add(
            BuffAddData(given_by=TAUNTER, applied_to=ENEMY, buff_id="도발")
        )
        _suppress(ctx)
        _enemy_attacks_ally(ctx, manager)
        assert _damage_taken(ctx, ALLY) == 0
        assert _damage_taken(ctx, TAUNTER) > 0


class TestMaxAttackRollPassive:
    def test_roll_is_not_fixed(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 1)
        ctx = _context(_buff_mod_passive(BuffMaxAttackRoll, ENEMY))
        manager = _manager(ctx)
        _add(ctx, "적군", FactionType.ENEMY, 0, passive_skill_id=PASSIVE_ID)
        _add(ctx, "아군", FactionType.ALLY, 0)
        _suppress(ctx)
        _enemy_attacks_ally(ctx, manager)
        assert _damage_taken(ctx, ALLY) == 5 + 1


class TestStripBuffsOnHitPassive:
    def test_target_buffs_survive(self):
        ctx = _context(
            _buff_mod_passive(BuffStripBuffsOnHit, ENEMY),
            buff_dict={
                "버프_1": _buff_data("버프_1", "BuffReceivedDamage", BuffType.BUFF)
            },
        )
        manager = _manager(ctx)
        _add(ctx, "적군", FactionType.ENEMY, 0, passive_skill_id=PASSIVE_ID)
        _add(ctx, "아군", FactionType.ALLY, 0)
        ctx.buff_container.add(
            BuffAddData(given_by=ALLY, applied_to=ALLY, buff_id="버프_1")
        )
        _suppress(ctx)
        _enemy_attacks_ally(ctx, manager)
        assert ctx.buff_container.get_buff(ALLY, "버프_1") is not None


class TestEffectsPassive:
    """스킬 효과 경로(라운드 시작 트리거)."""

    def _setup(self):
        ctx = _context(
            _round_start_self_buff_passive(),
            buff_dict={
                SELF_BUFF_ID: _buff_data(SELF_BUFF_ID, "BuffAtk", BuffType.BUFF)
            },
        )
        _add(ctx, "적군", FactionType.ENEMY, 0, passive_skill_id=PASSIVE_ID)
        _add(ctx, "아군", FactionType.ALLY, 0)
        return ctx

    def test_round_start_passive_does_not_fire(self):
        ctx = self._setup()
        _suppress(ctx)
        ctx.on_start_round()
        assert ctx.buff_container.get_buff(ENEMY, SELF_BUFF_ID) is None

    def test_round_start_passive_fires_without_effect(self):
        ctx = self._setup()
        ctx.on_start_round()
        assert ctx.buff_container.get_buff(ENEMY, SELF_BUFF_ID) is not None


class TestFieldSheetLabel:
    def test_suppressed_passive_is_marked(self):
        ctx = _context(_round_start_self_buff_passive())
        _add(ctx, "적군", FactionType.ENEMY, 0, passive_skill_id=PASSIVE_ID)
        _add(ctx, "아군", FactionType.ALLY, 0, passive_skill_id=PASSIVE_ID)
        _suppress(ctx)

        enemy_text, _ = _format_buff_cell(ctx, ENEMY)
        ally_text, _ = _format_buff_cell(ctx, ALLY)
        assert "(무효)" in enemy_text
        assert "(무효)" not in ally_text
