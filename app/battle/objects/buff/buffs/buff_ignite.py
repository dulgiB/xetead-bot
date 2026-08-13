from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Optional

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.buff.damage_factory import make_coefficient_damage_calc
from battle.objects.define import (
    BattlefieldColumnIndex,
    BuffApplyTiming,
    ValueSourceType,
)
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.command_calculator import CommandPartCalculator

# [발화]가 만료 시 입히는 대미지 계수(부여자 공격 굴림값 × N%)
_EXPIRE_DAMAGE_COEFFICIENT = 150.0


@dataclass(frozen=True)
class IgniteExpireEvent(BuffEvent):
    """[발화]가 이번 라운드 종료로 소멸할 때(remaining_turns가 1 -> 0이 되는
    라운드 종료 시점)만 발동한다. 대상이 부여 당시 스냅샷해둔 열에 그대로
    있으면 부여자 공격 굴림 기반 대미지를 입힌다."""

    column: int
    is_expiring_this_round: bool
    source_name: str

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if not self.is_expiring_this_round:
            return False
        if not super().is_applied(context, holder, attacker_or_target):
            return False
        return context.find_character_position(holder).value == self.column

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        calculator.data_by_effect[effect_seq_number].damage_data_list.append(
            make_coefficient_damage_calc(
                attacker_id=attacker_or_target,
                target_id=holder,
                value_source=ValueSourceType.STAT_ATK_ROLL,
                source_name=self.source_name,
                coefficient_value=_EXPIRE_DAMAGE_COEFFICIENT,
            )
        )


class BuffIgnite(BuffBase):
    """[발화: N열]: 부여 시점 대상의 열을 value에 스냅샷해두는 디버프.

    지속시간이 끝나는(remaining_turns가 0이 되는) 라운드 종료 시점에 대상이
    그 열에 그대로 있으면 부여자의 공격 굴림 150%만큼 대미지를 입힌다. 서로
    다른 열로 부여되면 별개의 인스턴스로 동시에 유지된다
    (PARTITION_UID_BY_VALUE=True). 같은 열로 재부여하면 기존과 동일하게
    지속시간만 갱신된다.
    """

    PARTITION_UID_BY_VALUE: ClassVar[bool] = True

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ROUND_END

    def create_event(self) -> IgniteExpireEvent:
        return IgniteExpireEvent(
            condition=self.condition,
            column=self.value,
            is_expiring_this_round=self.duration.remaining_turns == 1,
            source_name=self.id,
        )

    def display_id_label(self) -> str:
        return f"{self.id}: {BattlefieldColumnIndex(self.value)}열"
