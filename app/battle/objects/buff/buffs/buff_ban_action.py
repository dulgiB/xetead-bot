from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from battle.core.commands.models import CommandCalculator
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import ActionType, BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True)
class BanActionEvent(BuffEvent):
    banned_actions: list[ActionType]

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        context: "BattlefieldContext",
        calculator: CommandCalculator,
    ) -> None:
        calculator.ban_event_list.append(self)


class BuffBanAction(BuffBase):
    @cached_property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_ATTACK, BuffApplyTiming.ON_MOVE}

    def apply(self) -> BanActionEvent:
        return BanActionEvent(
            condition=self.condition,
            banned_actions=[
                ActionType.MOVE,
                ActionType.ATTACK,
                ActionType.SKILL_1,
                ActionType.SKILL_2,
                ActionType.SKILL_3,
                ActionType.USE_ITEM,
            ],
        )
