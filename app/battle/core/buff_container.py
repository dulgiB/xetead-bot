from typing import TYPE_CHECKING, Optional

from battle.core.command_calculator import CommandPartCalculator

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.buff.buff_base import (
        BuffAddData,
        BuffBase,
    )

from battle.objects.buff.buff_base import BuffDurationCounter
from battle.objects.define import BuffApplyTiming
from battle.objects.models import BuffUid, CharacterId


class BuffContainer:
    def __init__(self, field: "BattlefieldContext"):
        self._context: "BattlefieldContext" = field
        self._buffs: set[BuffBase] = set()

    def add(self, add_event: "BuffAddData"):
        buff_data = self._context.get_buff_data_by_id(add_event.buff_id)
        target_uid = BuffUid(
            add_event.given_by, add_event.applied_to, buff_data.buff_class_name
        )
        existing = next((b for b in self._buffs if b.uid == target_uid), None)

        if existing is not None:
            # 적층 불가 버프도 재부여 시 지속시간은 갱신(리셋)한다.
            existing.duration = BuffDurationCounter(
                buff_data.duration_turn_value,
                buff_data.duration_count_value,
                buff_data.duration_count_deduct_condition,
            )
            if buff_data.max_stack is not None:
                existing.stack_count = min(
                    buff_data.max_stack, existing.stack_count + add_event.stack_value
                )
            return

        self._buffs.add(
            buff_data.to_buff_instance(
                add_event.given_by, add_event.applied_to, add_event.stack_value
            )
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

    def get_buff(self, char_id: CharacterId, buff_id: str) -> Optional["BuffBase"]:
        return next(
            (
                buff
                for buff in self._buffs
                if buff.applied_to == char_id and buff.id == buff_id
            ),
            None,
        )

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

    def on_character_damaged(
        self,
        damaged_char_id: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        """damaged_char_id가 대미지를 받을 때, 같은 진영·같은 열(자신 포함)에
        있는 캐릭터가 보유한 ALLY_DAMAGED 타이밍 버프를 발동한다. 도구는 이미
        처리 중인 calculator/effect_seq_number를 그대로 재사용해, 반응으로
        추가되는 버프/대미지/힐이 같은 effect의 로그에 함께 기록되게 한다."""
        damaged_char = self._context.characters.get(damaged_char_id)
        if damaged_char is None:
            return
        self._context.damaged_this_round.add(damaged_char_id)
        damaged_pos = self._context.find_character_position(damaged_char_id)

        event_pairs = []
        for buff in self._buffs:
            if buff.timing != BuffApplyTiming.ALLY_DAMAGED:
                continue
            holder_char = self._context.characters.get(buff.applied_to)
            if holder_char is None:
                continue
            if holder_char.faction != damaged_char.faction:
                continue
            if self._context.find_character_position(buff.applied_to) != damaged_pos:
                continue
            event_pairs.append((buff.create_event(), buff.applied_to))

        if not event_pairs:
            return

        event_pairs.sort(key=lambda x: x[0].priority.value)
        for event, holder in event_pairs:
            if event.is_applied(self._context, holder, damaged_char_id):
                event.apply(holder, damaged_char_id, calculator, effect_seq_number)

    def on_battle_end(self) -> None:
        """전투 종료 시점에 모든 버프의 on_battle_end() 훅을 호출한다."""
        for buff in list(self._buffs):
            buff.on_battle_end(self._context)

    def on_enemy_post_action(self) -> None:
        self._apply_round_events(BuffApplyTiming.ON_ENEMY_POST_ACTION)

    def on_enemy_post_action_resolved(self) -> None:
        self._apply_round_events(BuffApplyTiming.ON_ENEMY_POST_ACTION_RESOLVED)

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
