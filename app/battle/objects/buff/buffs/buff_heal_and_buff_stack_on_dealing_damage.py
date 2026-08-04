from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from battle.core.commands.models import HealCalculateData
from battle.objects.buff.buff_base import BuffAddData, BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import (
    ActionType,
    BuffApplyTiming,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    FloatValueModifier,
    HealData,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class HealAndBuffStackOnDealingDamageEvent(BuffEvent):
    """holder가 대미지를 줄 때마다 그 대미지의 heal_percent%만큼 자신을
    회복시키고, 회복량이 _STACK_HEAL_THRESHOLD 이상이거나 대상이 holder와
    같은 진영(아군)이면 reference_buff_id 버프를 1스택 부여한다.
    ActionType.USE_ITEM(대미지를 주는 아이템 사용)은 직접 공격/스킬이
    아니므로 발동시키지 않는다.

    holder의 한 번의 공격이 단일 대상만 노린다고 가정한다 — 여러 대상을
    동시에 타격하는 효과라면 GIVEN_DAMAGE가 이 effect의 전체 대미지를
    합산하므로 대상별 회복량을 구분해서 판정할 수 없다.
    """

    _STACK_HEAL_THRESHOLD: ClassVar[int] = 5

    source_name: str
    heal_percent: int
    reference_buff_id: str

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        if calculator.action_type == ActionType.USE_ITEM:
            return

        context = calculator.context
        holder_char = context.characters.get(holder)
        if holder_char is None:
            return

        effect_data = calculator.data_by_effect[effect_seq_number]
        target_id = next(
            (
                damage_data.base.target_id
                for damage_data in effect_data.damage_data_list
                if damage_data.base.attacker_id == holder
                and damage_data.base.triggers_given_damage_passives
                and damage_data.base.target_id in context.characters
            ),
            None,
        )
        if target_id is None:
            return

        # _process_heal()이 방금 부여한 회복 항목의 healer/target(둘 다
        # holder 자신)에 대해 ON_ACTION 버프를 다시 조회하면서 이 이벤트를
        # 재호출하기 때문에(회복 모디파이어 버프를 위한 정상 훅), 아무런
        # 가드 없이 매번 새 항목을 append하면 같은 행동 안에서 무한 증식한다
        # (PassiveSkillWrapperEvent의 GIVEN_DAMAGE/GIVEN_HEAL 이중 발동 방지와
        # 동일한 문제). effect당 1회만 발동하도록 계산기 수명 동안 기록한다.
        fire_key = (effect_seq_number, holder, "heal_and_buff_stack_on_dealing_damage")
        if fire_key in calculator._fired_given_value_passives:
            return
        calculator._fired_given_value_passives.add(fire_key)

        is_ally = context.characters[target_id].faction == holder_char.faction

        effect_data.heal_data_list.append(
            HealCalculateData(
                HealData(
                    healer_id=holder,
                    target_id=holder,
                    value=BaseValueIndicator(
                        value_source=ValueSourceType.GIVEN_DAMAGE,
                        coefficient=FloatValueModifier(
                            source_name=self.source_name, value=self.heal_percent
                        ),
                    ),
                )
            )
        )
        effect_data.buff_add_data_list.append(
            BuffAddData(
                given_by=holder,
                applied_to=holder,
                buff_id=self.reference_buff_id,
                gate_value_source=ValueSourceType.GIVEN_HEAL,
                gate_value=0 if is_ally else self._STACK_HEAL_THRESHOLD,
            )
        )


class BuffHealAndBuffStackOnDealingDamage(BuffBase):
    """대미지를 줄 때마다 그 대미지의 value%만큼 자신을 회복시키고, 그
    회복량이 일정 수준 이상이거나(내부 임계값 고정) 대상이 자신과 같은
    진영이면 reference_buff_id 버프를 1스택 부여하는 패시브 모디파이어.
    "버프_패시브" 시트의 buff_mod_event 경로 전용이다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> HealAndBuffStackOnDealingDamageEvent:
        if self.value_type != ValueType.PERCENT:
            raise ValueError(self.value_type)
        assert self.reference_buff_id is not None
        return HealAndBuffStackOnDealingDamageEvent(
            condition=self.condition,
            source_name=self.id,
            heal_percent=self.value,
            reference_buff_id=self.reference_buff_id,
        )
