from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.buff.buff_base import (
        BuffAddEvent,
        BuffBase,
        BuffRemoveEvent,
    )
    from battle.objects.buff.models import BuffData

from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId


class BuffContainer:
    def __init__(self, field: "BattlefieldContext"):
        self._context: "BattlefieldContext" = field
        self._buffs: set[BuffBase] = set()
        self._buff_module = __import__("battle.objects.buff.buffs", fromlist=[])
        self._buff_dictionary: dict[str, BuffData] = {}

    def add(self, add_event: "BuffAddEvent"):
        buff: Type[BuffBase] = getattr(self._buff_module, add_event.buff_name)
        self._buffs.add(
            buff(
                add_event.given_by,
                add_event.applied_to,
                self._buff_dictionary[add_event.buff_name],
            )
        )

    def remove(self, remove_event: "BuffRemoveEvent"):
        self._buffs = {buff for buff in self._buffs if buff.id != remove_event.buff_id}

    def clear(self):
        self._buffs = set()

    def get_buffs_by(self, char_id: CharacterId, timing: BuffApplyTiming):
        return [
            buff
            for buff in self._buffs
            if buff.applied_to == char_id and timing in buff.timing
        ]

    def on_round_end(self) -> list["BuffRemoveEvent"]:
        buffs_to_remove: list[BuffBase] = []

        for buff in self._buffs:
            buff.duration.deduct_turn()
            if buff.duration.finished:
                buffs_to_remove.append(buff)

        if buffs_to_remove:
            remove_event_list = [BuffRemoveEvent(buff.id) for buff in buffs_to_remove]
            for event in remove_event_list:
                self.remove(event)
            return remove_event_list

        return []
