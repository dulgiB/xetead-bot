from typing import TYPE_CHECKING, Optional

from battle.core.command_calculator import CommandPartCalculator

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

    def add_passive_wrapper(self, buff: "BuffBase") -> None:
        """PassiveSkillWrapperBuff 등록 전용. BuffData 없이 직접 생성된 인스턴스를 추가한다."""
        self._buffs.add(buff)

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

        buff_calculator = CommandPartCalculator.create_empty_for_buff(self._context)
        for event, given_by, applied_to in event_pairs:
            if event.is_applied(self._context, applied_to, given_by):
                event.apply(applied_to, given_by, buff_calculator, 0)
        buff_calculator.process(None)

    def on_voluntary_move(self, moved_char_id: CharacterId) -> None:
        """자발적 이동 시 ON_ENEMY_MOVE 타이밍 패시브를 발동한다. 강제 이동은 제외된다."""
        moved_char = self._context.characters.get(moved_char_id)
        if moved_char is None:
            return

        event_pairs = []
        for buff in self._buffs:
            if buff.timing != BuffApplyTiming.ON_ENEMY_MOVE:
                continue
            holder_char = self._context.characters.get(buff.applied_to)
            if holder_char is None:
                continue
            if holder_char.faction == moved_char.faction:
                continue
            event_pairs.append((buff.create_event(), buff.applied_to))

        if not event_pairs:
            return

        event_pairs.sort(key=lambda x: x[0].priority.value)
        buff_calculator = CommandPartCalculator.create_empty_for_buff(self._context)
        for event, holder in event_pairs:
            if event.is_applied(self._context, holder, moved_char_id):
                event.apply(holder, moved_char_id, buff_calculator, 0)
        buff_calculator.process(None)

    def on_enemy_post_action(self) -> None:
        self._apply_round_events(BuffApplyTiming.ON_ENEMY_POST_ACTION)

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
