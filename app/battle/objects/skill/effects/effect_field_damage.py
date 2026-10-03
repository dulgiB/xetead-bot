from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.define import ValueSourceType
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    DamageData,
    FloatValueModifier,
    HealData,
    MoveData,
)
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectFieldDamage(SkillEffectBase):
    """필드 효과 전용: 시전자 없이 고정 대미지를 입힌다.

    일반 대미지 효과(SkillEffectDamage 등)를 필드 효과에 쓸 수 없어 따로 둔다 —
    그쪽은 시전자의 공격 속성을 읽으려고 `context.characters[holder]`를 직접
    인덱싱하는데, 필드 효과의 홀더는 전장에 없는 센티넬이라 KeyError가 난다.

    같은 이유로 계수 대미지(공격력 × N%)도 지원하지 않는다. 곱할 공격력을
    가진 시전자가 없으므로 `value_N`은 고정 대미지 수치로 읽는다
    (`value_source_N`은 비워 둔다). 예외는 `참조 버프의 현재 스택 수`로,
    시전자가 아니라 **대상**에게서 읽는 값이라 필드 효과에도 쓸 수 있다 —
    그때 `value_N`은 스택당 대미지가 된다. 설명이 "고정"이라 부르는 대미지인
    만큼 주는/받는 대미지 버프의 배율은 받지 않는다.

    속성은 물리로 고정한다. 마법 저항은 시전자의 공격 속성에 대응하는 방어
    스탯인데 필드 효과에는 대응할 시전자가 없어, 마법으로 두면 마법 저항
    보유자만 전장 자체의 피해를 덜 받는 납득하기 어려운 상태가 된다.
    """

    requires_holder_character: ClassVar[bool] = False

    def _expand(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
        raw_targets: tuple = (),
    ) -> tuple[
        list[MoveData],
        list[DamageData],
        list[HealData],
        list[BuffAddData],
        list[BuffRemoveData],
    ]:
        assert self.value is not None

        if self.value_source == ValueSourceType.REFERENCED_BUFF_STACK:
            assert self.reference_buff_id is not None
            reference_buff_id = self.reference_buff_id
            # 라운드 시작처럼 범위 전원에게 걸리는 트리거에서는 스택이 없는
            # 대상마다 "대미지 0" 결과 줄이 생긴다.
            targets = [
                target
                for target in targets
                if context.get_buff_stack(target, reference_buff_id) > 0
            ]
            damage_value = BaseValueIndicator(
                ValueSourceType.REFERENCED_BUFF_STACK,
                coefficient=FloatValueModifier(
                    source_name="스택당 대미지", value=self.value * 100
                ),
                consumed_buff_id=reference_buff_id,
                ignores_value_modifiers=True,
            )
        else:
            damage_value = BaseValueIndicator(ValueSourceType.FIXED, self.value)
        return (
            [],
            [
                DamageData(
                    attacker_id=holder,
                    target_id=target,
                    value=damage_value,
                    is_magic_attack=False,
                    # 필드 효과는 도발로 끌어올 수 있는 공격이 아니다 — 전장
                    # 자체가 범위 전원에게 직접 가하는 피해다.
                    ignores_taunt=True,
                )
                for target in targets
            ],
            [],
            [],
            [],
        )
