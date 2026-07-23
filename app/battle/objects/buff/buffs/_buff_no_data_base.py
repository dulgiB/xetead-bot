import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class NoDataEvent(BuffEvent, abc.ABC):
    # 무효화 로그(예: "[방어막] 소모, 대미지 없음")에 표시할 버프 라벨.
    buff_label: str

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.POST

    @property
    @abc.abstractmethod
    def _effect_label(self) -> str:
        """무효화 로그에 붙일 효과 이름 (예: "대미지", "회복")."""
        pass

    @abc.abstractmethod
    def _get_data_list(
        self, calculator: "CommandPartCalculator", effect_seq_number: int
    ) -> list:
        pass

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        data_list = self._get_data_list(calculator, effect_seq_number)
        to_remove = [d for d in data_list if d.base.target_id == holder]
        for d in to_remove:
            data_list.remove(d)
        if to_remove:
            calculator.data_by_effect[effect_seq_number].nullified_effect_list.append(
                (holder, f"[{self.buff_label}] 소모, {self._effect_label} 없음")
            )


class BuffNoDataBase(BuffBase, abc.ABC):
    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION
