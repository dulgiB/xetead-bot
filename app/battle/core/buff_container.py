import importlib
from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.buff.buff_base import (
        BuffAddData,
        BuffBase,
    )

from battle.objects.define import BuffApplyTiming
from battle.objects.models import BuffId, CharacterId


class BuffContainer:
    def __init__(self, field: "BattlefieldContext"):
        self._context: "BattlefieldContext" = field
        self._buffs: set[BuffBase] = set()
        self._buff_module = importlib.import_module("battle.objects.buff.buffs")

    def add(self, add_event: "BuffAddData"):
        buff: Type[BuffBase] = getattr(self._buff_module, add_event.buff_name)
        self._buffs.add(
            buff(
                add_event.given_by,
                add_event.applied_to,
                self._context.get_buff_data_by_id(add_event.buff_name),
            )
        )

    def clear(self):
        self._buffs = set()

    def get_buffs_by(self, char_id: CharacterId, timing: BuffApplyTiming):
        return [
            buff
            for buff in self._buffs
            if buff.applied_to == char_id and timing in buff.timing
        ]

    def on_round_end(self) -> list[BuffId]:
        buffs_to_remove: list[BuffBase] = []

        for buff in self._buffs:
            buff.duration.deduct_turn()
            if buff.duration.finished:
                buffs_to_remove.append(buff)

        if buffs_to_remove:
            for buff in buffs_to_remove:
                self._buffs.remove(buff)
            return [buff.id for buff in buffs_to_remove]

        return []
