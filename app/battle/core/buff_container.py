from typing import TYPE_CHECKING, Optional

from battle.core.command_process_helpers import (
    process_damage,
    process_heal,
    process_move,
)
from battle.core.commands.models import CommandPartCalculator

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.buff.buff_base import (
        BuffAddData,
        BuffBase,
    )

from battle.objects.define import BuffApplyTiming
from battle.objects.models import BuffUid, CharacterId


class BuffContainer:
    def __init__(self, field: "BattlefieldContext"):
        self._context: "BattlefieldContext" = field
        self._buffs: set[BuffBase] = set()

    def add(self, add_event: "BuffAddData"):
        buff_data = self._context.get_buff_data_by_id(add_event.buff_id)
        self._buffs.add(
            buff_data.to_buff_instance(add_event.given_by, add_event.applied_to)
        )

    def remove(self, buff_uid: BuffUid) -> None:
        for buff in self._buffs:
            if buff.uid == buff_uid:
                self._buffs.remove(buff)
                return

    def clear(self):
        self._buffs = set()

    def get_buffs_by(self, char_id: CharacterId, timing: Optional[BuffApplyTiming]):
        if timing is None:
            return [buff for buff in self._buffs if buff.applied_to == char_id]
        else:
            return [
                buff
                for buff in self._buffs
                if buff.applied_to == char_id and timing == buff.timing
            ]

    def _apply_round_events(self, timing: BuffApplyTiming) -> None:
        event_pairs = [
            (buff.create_event(), buff.given_by, buff.applied_to)
            for buff in self._buffs
            if buff.timing == timing
        ]
        event_pairs.sort(key=lambda x: x[0].priority.value)

        buff_calculator = CommandPartCalculator.create_empty(self._context)
        for event, given_by, applied_to in event_pairs:
            if event.is_applied(self._context, applied_to, given_by):
                event.apply(applied_to, given_by, self._context, buff_calculator)

        process_move(buff_calculator, self._context)
        process_damage(buff_calculator, self._context)
        process_heal(buff_calculator, self._context)

    def on_round_start(self):
        self._apply_round_events(BuffApplyTiming.ON_ROUND_START)

    def on_round_end(self) -> list[BuffUid]:
        self._apply_round_events(BuffApplyTiming.ON_ROUND_END)

        buffs_to_remove: list[BuffBase] = []
        for buff in self._buffs:
            buff.duration.deduct_turn()
            if buff.duration.finished:
                buffs_to_remove.append(buff)

        if buffs_to_remove:
            for buff in buffs_to_remove:
                self._buffs.remove(buff)
            return [buff.uid for buff in buffs_to_remove]

        return []
