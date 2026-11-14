from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, CombatStatType, ValueType
from battle.objects.models import CharacterId, IntValueModifier

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class AtkModEvent(BuffEvent):
    supports_target_scope: ClassVar[bool] = True

    value: IntValueModifier

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
        # 대상별 판정 중이면 그 대상을 칠 때의 공격력에만 얹는다. 피격 쪽
        # 디스패치(holder가 대상)는 공격력을 읽지 않으므로 구분하지 않는다.
        scope = calculator.event_target_scope
        if scope is not None:
            calculator.scoped_atk_bonuses.setdefault((holder, scope), []).append(
                self.value
            )
            return
        calculator.buffed_stats_by_character[holder].stat_bonuses[
            CombatStatType.ATK
        ].append(self.value)


class BuffAtk(BuffBase):
    """공격력 증가/감소.

    조건만 다른 공격력 증가를 같은 부여자가 함께 거는 일이 있어(이동 여부·
    거리 조건 등) 행(id)이 다르면 따로 유지한다."""

    PARTITION_UID_BY_ID: ClassVar[bool] = True

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> AtkModEvent:
        if self.value_type == ValueType.INTEGER:
            return AtkModEvent(
                condition=self.condition,
                value=IntValueModifier(source_name=self.id, value=self.value),
            )
        else:
            raise ValueError(self.value_type)
