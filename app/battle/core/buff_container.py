from typing import TYPE_CHECKING, Callable, Optional

from utils.battle_helpers import is_reachable

from battle.core.command_calculator import CommandPartCalculator, build_log_entries
from battle.core.commands.models import BattleLogEntry

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.buff.buff_base import (
        BuffAddData,
        BuffBase,
    )
    from battle.objects.buff.buff_events import BuffEvent

from battle.objects.buff.buff_base import BuffDurationCounter
from battle.objects.define import BuffApplyTiming, CombatStatType, FactionType
from battle.objects.models import BuffUid, CharacterId


class BuffContainer:
    def __init__(self, field: "BattlefieldContext"):
        self._context: "BattlefieldContext" = field
        self._buffs: set[BuffBase] = set()
        # 도발처럼 같은 대상이 서로 다른 부여자로부터 동시에 여러 인스턴스를
        # 받을 수 있는 버프에서 "가장 최근에 걸린 것"을 가려내기 위한
        # 단조 증가 일련번호. add()가 새로 추가하거나 기존 인스턴스를
        # 재부여(갱신)할 때마다 부여한다 — 재부여도 "다시 최근이 됨"으로
        # 취급한다.
        self._apply_seq = 0

    def _next_apply_seq(self) -> int:
        self._apply_seq += 1
        return self._apply_seq

    def add(self, add_event: "BuffAddData"):
        buff_data = self._context.get_buff_data_by_id(add_event.buff_id)
        buff_class = buff_data.get_buff_class()
        # PARTITION_UID_BY_VALUE인 버프는 이번에 부여될 값(재정의 우선)이
        # 기존 인스턴스와 달라야 별개로 유지된다 — build_uid()가 uid 계산을
        # BuffBase.__init__과 동일한 규칙으로 공유한다.
        uid_value = (
            add_event.value_override
            if add_event.value_override is not None
            else buff_data.value
        )
        target_uid = buff_class.build_uid(
            add_event.given_by,
            add_event.applied_to,
            buff_data.buff_class_name,
            uid_value,
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
            if add_event.value_override is not None:
                existing.value = add_event.value_override
            existing.applied_at = self._next_apply_seq()
            return

        new_buff = buff_data.to_buff_instance(
            add_event.given_by,
            add_event.applied_to,
            add_event.stack_value,
            value_override=add_event.value_override,
        )
        new_buff.applied_at = self._next_apply_seq()
        self._buffs.add(new_buff)

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

    def get_buff(
        self,
        char_id: CharacterId,
        buff_id: str,
        given_by: Optional[CharacterId] = None,
    ) -> Optional["BuffBase"]:
        """(applied_to, id) 조합은 여러 부여자가 각자 별개 인스턴스로 동시에
        보유할 수 있다(도발 등 — 기본 build_uid()가 given_by를 포함하므로).
        given_by를 생략하면(None) 그중 아무 인스턴스나(내부 set 순서 의존,
        비결정적) 반환하므로, 특정 부여자의 인스턴스가 필요한 호출측은
        반드시 given_by를 넘겨야 한다."""
        return next(
            (
                buff
                for buff in self._buffs
                if buff.applied_to == char_id
                and buff.id == buff_id
                and (given_by is None or buff.given_by == given_by)
            ),
            None,
        )

    def _apply_round_events(self, timing: BuffApplyTiming) -> list[BattleLogEntry]:
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
        return build_log_entries(buff_calculator)

    def _collect_reactive_event_pairs(
        self,
        timing: BuffApplyTiming,
        required_faction: FactionType,
        in_scope: Callable[[CharacterId], bool],
    ) -> list[tuple["BuffEvent", CharacterId]]:
        """timing이 일치하고, holder의 진영이 required_faction과 같으며,
        in_scope(holder_id)가 True인 버프들의 (event, holder_id) 목록을
        priority 순으로 정렬해 반환한다. "같은 열"/"사거리 내" 등 범위
        판정 방식만 다른 반응형 트리거들(on_character_damaged 등)이 공유한다."""
        event_pairs = [
            (buff.create_event(), buff.applied_to)
            for buff in self._buffs
            if buff.timing == timing
            and (holder_char := self._context.characters.get(buff.applied_to))
            is not None
            and holder_char.faction == required_faction
            and in_scope(buff.applied_to)
        ]
        event_pairs.sort(key=lambda x: x[0].priority.value)
        return event_pairs

    def _apply_reactive_events(
        self,
        event_pairs: list[tuple["BuffEvent", CharacterId]],
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        for event, holder in event_pairs:
            if event.is_applied(self._context, holder, attacker_or_target):
                event.apply(holder, attacker_or_target, calculator, effect_seq_number)

    def _is_in_range_of(self, holder_id: CharacterId, target_pos) -> bool:
        holder_char = self._context.characters[holder_id]
        holder_pos = self._context.find_character_position(holder_id)
        holder_range = holder_char.status[CombatStatType.RANGE]
        return is_reachable(holder_pos, target_pos, holder_range)

    def on_enemy_move(
        self,
        moved_char_id: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        """이동 시(자발적/강제 모두) ON_ENEMY_MOVE 타이밍 패시브/버프를 발동한다.

        대미지 적용은 지금처럼 별도의 즉시-확정 계산기로 처리해 이동 종류
        (PRE 선언/강제 이동 등)에 관계없이 항상 그 자리에서 HP에 반영되게
        하되, 그 결과 로그는 이동을 유발한 calculator/effect_seq_number의
        extra_log_entries에 실어 build_log_entries()가 같은 CommandPart의
        로그로 함께 내보내게 한다(같은 calculator/effect를 그대로 재사용하지
        않는 이유는 command_calculator.py의 PRE/POST 분기 참고 — 적이 스스로
        선언한 이동은 PRE에서 _process_damage가 호출되지 않아 대미지가
        누락된다).
        """
        moved_char = self._context.characters.get(moved_char_id)
        if moved_char is None:
            return

        event_pairs = self._collect_reactive_event_pairs(
            BuffApplyTiming.ON_ENEMY_MOVE, moved_char.foe_faction, lambda _: True
        )
        if not event_pairs:
            return

        buff_calculator = CommandPartCalculator.create_empty_for_buff(self._context)
        for event, holder in event_pairs:
            if event.is_applied(self._context, holder, moved_char_id):
                event.apply(holder, moved_char_id, buff_calculator, 0)
        buff_calculator.process(None)

        calculator.data_by_effect[effect_seq_number].extra_log_entries.extend(
            build_log_entries(buff_calculator)
        )

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

        event_pairs = self._collect_reactive_event_pairs(
            BuffApplyTiming.ALLY_DAMAGED,
            damaged_char.faction,
            lambda holder_id: (
                self._context.find_character_position(holder_id) == damaged_pos
            ),
        )
        self._apply_reactive_events(
            event_pairs, damaged_char_id, calculator, effect_seq_number
        )

    def on_ally_in_range_damaged(
        self,
        damaged_char_id: CharacterId,
        attacker_id: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        """damaged_char_id가 대미지를 받을 때, holder의 사거리 이내(자신 포함)·
        같은 진영인 캐릭터가 보유한 ALLY_IN_RANGE_DAMAGED 타이밍 버프를
        발동한다. on_character_damaged(ALLY_DAMAGED, 같은 열 기준)와 달리
        사거리를 기준으로 한다는 점만 다르다.

        이벤트의 attacker_or_target에는 공격자(attacker_id)를 전달한다 —
        반격 등 홀더가 공격자에게 무언가를 하는 반응을 표현하기 쉽도록.
        """
        damaged_char = self._context.characters.get(damaged_char_id)
        if damaged_char is None or attacker_id not in self._context.characters:
            return
        damaged_pos = self._context.find_character_position(damaged_char_id)

        event_pairs = self._collect_reactive_event_pairs(
            BuffApplyTiming.ALLY_IN_RANGE_DAMAGED,
            damaged_char.faction,
            lambda holder_id: self._is_in_range_of(holder_id, damaged_pos),
        )
        self._apply_reactive_events(
            event_pairs, attacker_id, calculator, effect_seq_number
        )

    def on_ally_in_range_attacked(
        self,
        attacker_id: CharacterId,
        target_id: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        """attacker_id가 target_id를 공격할 때, holder의 사거리 이내·같은
        진영인 캐릭터(자신 포함)가 보유한 ALLY_IN_RANGE_ATTACKED 타이밍
        버프를 발동한다. holder 자신이 공격자가 아니어도 발동한다는 점에서
        일반 ON_ACTION(ON_ATTACK) 버프와 다르다.

        이벤트의 attacker_or_target에는 공격 대상(target_id)을 전달한다 —
        "그 대상에게도 대미지를 입힌다" 같은 반응을 표현하기 쉽도록.
        """
        attacker_char = self._context.characters.get(attacker_id)
        if attacker_char is None or target_id not in self._context.characters:
            return
        attacker_pos = self._context.find_character_position(attacker_id)

        event_pairs = self._collect_reactive_event_pairs(
            BuffApplyTiming.ALLY_IN_RANGE_ATTACKED,
            attacker_char.faction,
            lambda holder_id: self._is_in_range_of(holder_id, attacker_pos),
        )
        self._apply_reactive_events(
            event_pairs, target_id, calculator, effect_seq_number
        )

    def on_battle_end(self) -> list[BattleLogEntry]:
        """전투 종료 시점에 모든 버프의 on_battle_end() 훅을 호출하고,
        정산 결과가 있는 것들을 모아 반환한다."""
        entries = []
        for buff in list(self._buffs):
            entry = buff.on_battle_end(self._context)
            if entry is not None:
                entries.append(entry)
        return entries

    def on_enemy_post_action(self) -> None:
        self._apply_round_events(BuffApplyTiming.ON_ENEMY_POST_ACTION)

    def on_enemy_post_action_resolved(self) -> None:
        self._apply_round_events(BuffApplyTiming.ON_ENEMY_POST_ACTION_RESOLVED)

    def on_battle_start(self) -> None:
        self._apply_round_events(BuffApplyTiming.ON_BATTLE_START)

    def on_round_start(self):
        self._apply_round_events(BuffApplyTiming.ON_ROUND_START)

    def on_round_end(self) -> tuple[list[BattleLogEntry], list[BuffUid]]:
        log_entries = self._apply_round_events(BuffApplyTiming.ON_ROUND_END)

        buffs_to_remove: list[BuffBase] = []
        for buff in self._buffs:
            buff.duration.deduct_turn()
            if buff.duration.finished:
                buffs_to_remove.append(buff)

        if buffs_to_remove:
            for buff in buffs_to_remove:
                self._buffs.remove(buff)
            return log_entries, [buff.uid for buff in buffs_to_remove]

        return log_entries, []
