"""필드 효과 시트 설정 검증.

"스킬_패시브" 시트 하나를 캐릭터 패시브와 필드 효과가 함께 쓰므로, 한쪽
전용 값이 다른 쪽에 들어가도 로드는 성공한다. 그 어긋남은 전투 중에야
"아무 일도 일어나지 않음"으로 드러나 원인을 짚기 어려우므로, 개시 시점에
admin에게 알린다.
"""

from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
    character_passive_config_error,
    field_effect_config_error,
)
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectDamage,
    SkillEffectFieldDamage,
)


class _DummyEvent(BuffEvent):
    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(self, holder, attacker_or_target, calculator, effect_seq_number) -> None:
        pass


def _passive(
    target_type: PassiveSkillTargetType,
    effects: list,
    buff_mod_event=None,
) -> PassiveSkillData:
    return PassiveSkillData(
        id="FieldEffect",
        trigger=PassiveSkillTrigger.ROUND_START,
        target_type=target_type,
        effects=effects,
        description="",
        buff_mod_event=buff_mod_event,
    )


def _add_buff() -> SkillEffectAddBuff:
    return SkillEffectAddBuff(
        value_source=None,
        value=None,
        value_type=None,
        buff_id="AnyBuff",
        buff_add_timing=None,
    )


def _plain_damage() -> SkillEffectDamage:
    return SkillEffectDamage(
        value_source=None, value=10, value_type=None, buff_id=None, buff_add_timing=None
    )


def _field_damage() -> SkillEffectFieldDamage:
    return SkillEffectFieldDamage(
        value_source=None, value=10, value_type=None, buff_id=None, buff_add_timing=None
    )


class TestFieldEffectConfig:
    def test_holder_dependent_effect_is_reported(self):
        data = _passive(PassiveSkillTargetType.FIELD_ALL, [_plain_damage()])

        error = field_effect_config_error(data)

        assert error is not None
        assert "SkillEffectDamage" in error

    def test_field_safe_effects_are_accepted(self):
        data = _passive(
            PassiveSkillTargetType.FIELD_ALL, [_add_buff(), _field_damage()]
        )

        assert field_effect_config_error(data) is None

    def test_buff_mod_event_is_reported(self):
        """버프 모디파이어는 보유자에게만 걸리는데 필드 효과의 보유자는
        전장에 없는 자리다."""
        data = _passive(
            PassiveSkillTargetType.FIELD_ALLY_SIDE,
            [],
            buff_mod_event=_DummyEvent(condition=None),
        )

        error = field_effect_config_error(data)

        assert error is not None
        assert "buff_id" in error

    def test_character_passive_is_not_checked(self):
        data = _passive(PassiveSkillTargetType.SELF, [_plain_damage()])

        assert field_effect_config_error(data) is None


class TestCharacterPassiveConfig:
    def test_field_scope_on_a_character_passive_is_reported(self):
        data = _passive(PassiveSkillTargetType.FIELD_ALL, [_add_buff()])

        error = character_passive_config_error(data)

        assert error is not None
        assert "캐릭터 패시브로 쓸 수 없습니다" in error

    def test_ordinary_passive_is_accepted(self):
        data = _passive(PassiveSkillTargetType.ALL_ALLIES, [_add_buff()])

        assert character_passive_config_error(data) is None
