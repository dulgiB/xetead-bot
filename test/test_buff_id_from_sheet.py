"""구현체가 알아야 하는 버프 id는 코드 상수가 아니라 시트 컬럼에서 와야 한다.

예전에는 두 곳이 특정 버프 id("버프" 시트의 행 이름)를 클래스 상수로 들고
있었다. 그러면 시트만 봐서는 그 행이 실제로 쓰이는지 알 수 없어, 아무도
참조하지 않는 행으로 보고 지우면 효과가 조용히 사라진다(실제로 한 번
일어났다). 지금은 둘 다 reference_buff_id를 거치므로, 이 테스트는 그
경로가 유지되는지와 컬럼을 비웠을 때의 동작을 함께 고정한다.
"""

from battle.objects.buff.buffs import BuffGivenDamageAgainstDebuff
from battle.objects.buff.models import PassiveBuffData
from battle.objects.models import CharacterId
from battle.objects.skill.effects import (
    SkillEffectShieldOrReflectIfTargetHasFormationBuff,
)
from battle.objects.skill.models import SkillData

BASE_BUFF = "기본버프"
ALT_BUFF = "대체버프"
BONUS_BUFF = "추가조건버프"


def _shield_or_reflect(
    reference_buff_id: str,
) -> SkillEffectShieldOrReflectIfTargetHasFormationBuff:
    skill = SkillData.from_dict(
        {
            "id": "Skill",
            "description": "",
            "target_rule": "SkillTargetRuleAllyColumn",
            "target_count": 1,
            "cost": 3,
            "effect_0": "SkillEffectShieldOrReflectIfTargetHasFormationBuff",
            "value_source_0": "",
            "value_0": "",
            "value_type_0": "",
            "buff_id_0": BASE_BUFF,
            "reference_buff_id_0": reference_buff_id,
        }
    )
    effect = skill.effects[0]
    assert isinstance(effect, SkillEffectShieldOrReflectIfTargetHasFormationBuff)
    return effect


def test_alternate_buff_id_comes_from_reference_buff_id_column():
    assert _shield_or_reflect(ALT_BUFF).reference_buff_id == ALT_BUFF


def test_alternate_buff_is_not_applied_when_the_column_is_empty(
    empty_context, buff_atk_data
):
    """컬럼을 비우면 게이트 버프 보유 여부와 무관하게 항상 기본 버프만 부여한다 —
    비어 있는데 예전 상수로 되돌아가면 안 된다."""
    effect = _shield_or_reflect("")
    holder, target = CharacterId("A"), CharacterId("B")
    _, _, _, buff_add_list, _ = effect.expand(empty_context, holder, [target])
    assert [b.buff_id for b in buff_add_list] == [BASE_BUFF]


def _given_damage_against_debuff(reference_buff_id: str):
    data = PassiveBuffData.from_dict(
        {
            "id": "PassiveBuff",
            "buff_name": "BuffGivenDamageAgainstDebuff",
            "value_0": 20,
            "value_type_0": "퍼센트",
            "value_1": 5,
            "condition": "TargetHasDebuffCondition",
            "condition_value": "",
            "reference_buff_id": reference_buff_id,
        }
    )
    buff = BuffGivenDamageAgainstDebuff._create_bare(
        id_=data.id,
        uid=None,
        given_by=CharacterId("A"),
        applied_to=CharacterId("A"),
        value=data.value,
        value_type=data.value_type,
        value_2=data.value_2,
        condition=data.condition,
        reference_buff_id=data.reference_buff_id,
    )
    return buff.create_event()


def test_bonus_buff_id_comes_from_reference_buff_id_column():
    assert _given_damage_against_debuff(BONUS_BUFF).bonus_buff_id == BONUS_BUFF


def test_bonus_is_disabled_when_the_column_is_empty():
    """컬럼을 비우면 추가 증가분의 조건이 사라져 기본 증가분만 남는다."""
    assert _given_damage_against_debuff("").bonus_buff_id is None
