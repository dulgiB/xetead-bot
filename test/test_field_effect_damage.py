"""필드 효과의 고정 대미지.

일반 대미지 효과는 시전자의 공격 속성을 읽으려 `context.characters[holder]`를
직접 인덱싱하므로 홀더 없는 필드 효과에서 KeyError가 난다. 대미지 처리부도
공격자가 전장에 있는지로 "이미 사망한 항목"을 가리므로, 필드 효과의 센티넬
공격자를 통과시키지 않으면 항목이 조용히 사라진다. 그 두 지점이 이 테스트의
핵심이다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    MagicResistanceType,
    ValueSourceType,
    ValueType,
)
from battle.objects.field_effect.models import FieldEffectSource
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import SkillEffectFieldDamage
from helpers import get_test_preset

EFFECT_ID = "FieldEffect"


def _field_damage_effect(
    amount: int = 5,
    target_type: PassiveSkillTargetType = PassiveSkillTargetType.FIELD_ALL,
    trigger: PassiveSkillTrigger = PassiveSkillTrigger.ROUND_START,
) -> PassiveSkillData:
    return PassiveSkillData(
        id=EFFECT_ID,
        trigger=trigger,
        target_type=target_type,
        effects=[
            SkillEffectFieldDamage(
                value_source=None,
                value=amount,
                value_type=None,
                buff_id=None,
                buff_add_timing=None,
            )
        ],
        description="",
    )


def _make_context(effect: PassiveSkillData) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={},
        skill_dict={},
        passive_skill_dict={effect.id: effect},
    )


def _hp(ctx: BattlefieldContext, name: str) -> int:
    return ctx.characters[CharacterId(name)].status.curr_hp


class TestRoundStartDamage:
    def _setup(self, amount: int = 5) -> BattlefieldContext:
        ctx = _make_context(_field_damage_effect(amount))
        ctx.add_character(
            get_test_preset("아군"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        return ctx

    def test_damages_everyone_in_scope(self):
        ctx = self._setup()
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.on_start_round()

        assert _hp(ctx, "아군") == 95
        assert _hp(ctx, "적군") == 95

    def test_repeats_each_round(self):
        ctx = self._setup()
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.on_start_round()
        ctx.on_start_round()

        assert _hp(ctx, "아군") == 90

    def test_removed_effect_stops_damaging(self):
        ctx = self._setup()
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.on_start_round()
        ctx.remove_field_effect(EFFECT_ID)

        ctx.on_start_round()

        assert _hp(ctx, "아군") == 95

    def test_scope_limits_who_is_damaged(self):
        ctx = _make_context(
            _field_damage_effect(5, PassiveSkillTargetType.FIELD_ENEMY_SIDE)
        )
        ctx.add_character(
            get_test_preset("아군"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.on_start_round()

        assert _hp(ctx, "아군") == 100
        assert _hp(ctx, "적군") == 95


class TestMagicResistanceIsNotApplied:
    """필드 대미지는 물리 속성으로 고정한다 — 마법 저항 보유자만 전장 자체의
    피해를 덜 받는 상태가 되면 안 된다."""

    def test_resistant_and_weak_take_the_same_damage(self):
        ctx = _make_context(_field_damage_effect(20))
        ctx.add_character(
            get_test_preset("저항", m_res=MagicResistanceType.STRONG),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("취약", m_res=MagicResistanceType.WEAK),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.on_start_round()

        assert _hp(ctx, "저항") == 80
        assert _hp(ctx, "취약") == 80


class TestReactiveFieldDamage:
    def test_mover_takes_damage(self):
        ctx = _make_context(
            _field_damage_effect(
                7,
                PassiveSkillTargetType.FIELD_SUBJECT,
                PassiveSkillTrigger.ON_ENEMY_MOVE,
            )
        )
        ctx.add_character(
            get_test_preset("이동자"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("가만히"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        manager = RoundManager(ctx)
        manager.process_command(
            ChangePhaseCommand(
                type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
            )
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("이동자"), "[이동/2]", ctx)
        )

        assert _hp(ctx, "이동자") == 93
        assert _hp(ctx, "가만히") == 100


class TestProducedDamageShape:
    """전개 결과 자체를 확인한다. 도발 리다이렉트는 **공격자**에게 걸린 도발을
    보는데 필드 효과의 공격자는 전장에 없는 센티넬이라 애초에 도발이 걸릴 수
    없다 — 그래서 시나리오 테스트로는 의도가 드러나지 않는다."""

    def test_damage_is_physical_and_ignores_taunt(self):
        ctx = _make_context(_field_damage_effect(5))
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        effect = ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        assert effect is not None

        _, damage_list, _, _, _ = effect.data.effects[0].expand(
            ctx, effect.holder_id, [CharacterId("대상")]
        )

        assert len(damage_list) == 1
        assert damage_list[0].attacker_id == effect.holder_id
        assert damage_list[0].is_magic_attack is False
        assert damage_list[0].ignores_taunt is True


STACK_BUFF_ID = "StackBuff"
DAMAGE_UP_BUFF_ID = "DamageUp"


def _stack_buff() -> BuffData:
    return BuffData(
        id=STACK_BUFF_ID,
        buff_class_name="BuffAtk",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=0,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.DEBUFF,
        description="",
        max_stack=10,
    )


def _damage_up_buff() -> BuffData:
    return BuffData(
        id=DAMAGE_UP_BUFF_ID,
        buff_class_name="BuffReceivedDamage",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=100,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.DEBUFF,
        description="",
    )


def _stack_damage_on_hit_effect(per_stack: int) -> PassiveSkillData:
    return PassiveSkillData(
        id=EFFECT_ID,
        trigger=PassiveSkillTrigger.ALLY_DAMAGED,
        target_type=PassiveSkillTargetType.FIELD_SUBJECT,
        effects=[
            SkillEffectFieldDamage(
                value_source=ValueSourceType.REFERENCED_BUFF_STACK,
                value=per_stack,
                value_type=None,
                buff_id=None,
                buff_add_timing=None,
                reference_buff_id=STACK_BUFF_ID,
            )
        ],
        description="",
    )


class TestDamagePerReferencedStackOnHit:
    """ "이 버프가 걸린 캐릭터는 공격받을 때마다 (자신의 스택 수 × N)만큼 고정
    대미지를 추가로 입는다"를 피격 시 트리거 + 사건 당사자 범위로 표현한다."""

    def _hp_after_attack(
        self,
        monkeypatch,
        *,
        with_effect: bool,
        stack: int,
        damage_up: bool = False,
        attacks: tuple[tuple[str, str], ...] = (("아군", "[공격/적군]"),),
    ) -> int:
        monkeypatch.setattr("random.randint", lambda a, b: 4)
        effect = _stack_damage_on_hit_effect(2)
        ctx = BattlefieldContext(
            buff_dict={
                STACK_BUFF_ID: _stack_buff(),
                DAMAGE_UP_BUFF_ID: _damage_up_buff(),
            },
            skill_dict={},
            passive_skill_dict={effect.id: effect},
        )
        ctx.add_character(
            get_test_preset("아군"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("아군_2"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        if with_effect:
            ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        if stack:
            ctx.buff_container.add(
                BuffAddData(
                    given_by=CharacterId("아군"),
                    applied_to=CharacterId("적군"),
                    buff_id=STACK_BUFF_ID,
                    stack_value=stack,
                )
            )
        if damage_up:
            ctx.buff_container.add(
                BuffAddData(
                    given_by=CharacterId("아군"),
                    applied_to=CharacterId("적군"),
                    buff_id=DAMAGE_UP_BUFF_ID,
                )
            )

        manager = RoundManager(ctx)
        manager.process_command(
            ChangePhaseCommand(
                type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
            )
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        for attacker, command in attacks:
            manager.process_command(
                parse_character_command(CharacterId(attacker), command, ctx)
            )
        return _hp(ctx, "적군")

    def test_adds_stack_times_value(self, monkeypatch):
        baseline = self._hp_after_attack(monkeypatch, with_effect=False, stack=3)
        boosted = self._hp_after_attack(monkeypatch, with_effect=True, stack=3)

        assert baseline - boosted == 3 * 2

    def test_no_stack_no_extra_damage(self, monkeypatch):
        baseline = self._hp_after_attack(monkeypatch, with_effect=False, stack=0)
        boosted = self._hp_after_attack(monkeypatch, with_effect=True, stack=0)

        assert baseline == boosted

    def test_extra_damage_ignores_received_damage_buffs(self, monkeypatch):
        """ "고정" 대미지이므로 받는 대미지 버프는 원래 공격에만 붙는다."""
        baseline = self._hp_after_attack(
            monkeypatch, with_effect=False, stack=3, damage_up=True
        )
        boosted = self._hp_after_attack(
            monkeypatch, with_effect=True, stack=3, damage_up=True
        )

        assert baseline - boosted == 3 * 2

    def test_applies_per_attack_from_same_attacker(self, monkeypatch):
        """중복 방지는 한 행동 안에서만 걸린다 — 공격을 두 번 하면 두 번 붙는다."""
        attacks = (("아군", "[공격/적군 - 공격/적군]"),)
        baseline = self._hp_after_attack(
            monkeypatch, with_effect=False, stack=3, attacks=attacks
        )
        boosted = self._hp_after_attack(
            monkeypatch, with_effect=True, stack=3, attacks=attacks
        )

        assert baseline - boosted == 2 * 3 * 2

    def test_applies_per_attacker(self, monkeypatch):
        attacks = (("아군", "[공격/적군]"), ("아군_2", "[공격/적군]"))
        baseline = self._hp_after_attack(
            monkeypatch, with_effect=False, stack=3, attacks=attacks
        )
        boosted = self._hp_after_attack(
            monkeypatch, with_effect=True, stack=3, attacks=attacks
        )

        assert baseline - boosted == 2 * 3 * 2
