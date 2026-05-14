from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import (
    CommandPartData,
    DamageCalculateData,
    HealCalculateData,
)
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.character.buffed_stats import BuffedStats
from battle.objects.define import (
    BuffApplyTiming,
    BuffCountDeductCondition,
    CombatStatType,
)
from battle.objects.models import (
    CharacterId,
    DamageData,
    HealData,
    MoveData,
    ValueWithModifiers,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass
class CalculatorMutableData:
    def __init__(
        self,
        move_list: list[MoveData],
        damage_list: list[DamageData],
        heal_list: list[HealData],
        buff_add_list: list[BuffAddData],
    ):
        self.move_list: list[MoveData] = move_list
        self.damage_data_list: list[DamageCalculateData] = [
            DamageCalculateData(damage_data, []) for damage_data in damage_list
        ]
        self.heal_data_list: list[HealCalculateData] = [
            HealCalculateData(heal_data, []) for heal_data in heal_list
        ]
        self.buff_add_data_list: list[BuffAddData] = buff_add_list


class CommandPartCalculator:
    def __init__(self, data: CommandPartData, context: "BattlefieldContext"):
        self.context = context
        self.buffed_stats_by_character: dict[CharacterId, BuffedStats] = {
            char_id: BuffedStats(
                character.status, {stat: [] for stat in CombatStatType}
            )
            for char_id, character in context.characters.items()
        }

        self.data_by_effect: list[CalculatorMutableData] = [
            CalculatorMutableData(
                data_per_effect.move_list,
                data_per_effect.damage_list,
                data_per_effect.heal_list,
                data_per_effect.buff_add_list,
            )
            for data_per_effect in data.data_per_effect
            if data_per_effect is not None
        ]

    @classmethod
    def create_empty_for_buff(
        cls, context: "BattlefieldContext"
    ) -> "CommandPartCalculator":
        empty = cls(
            CommandPartData(
                original_part=None,
                data_per_effect=tuple(),
            ),
            context,
        )
        empty.data_by_effect.append(CalculatorMutableData([], [], [], []))
        return empty

    def process(
        self,
        phase: Optional[RoundPhaseType],
    ):
        if phase == RoundPhaseType.ENEMY_PRE_ACTION:
            for i in range(len(self.data_by_effect)):
                self._process_move(i)
                self._process_buff_add(i, phase)

        elif phase == RoundPhaseType.ALLY_ACTION:
            for i in range(len(self.data_by_effect)):
                self._process_move(i)
                self._process_damage(i)
                self._process_heal(i)
                self._process_buff_add(i, phase)

        elif phase == RoundPhaseType.ENEMY_POST_ACTION:
            for i in range(len(self.data_by_effect)):
                self._process_damage(i)
                self._process_heal(i)
                self._process_buff_add(i, phase)

        elif phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
            pass

        else:
            # phase가 없다면 BuffContainer에서 호출한 경우
            for i in range(len(self.data_by_effect)):
                self._process_move(i)
                self._process_damage(i)
                self._process_heal(i)

    def _process_move(self: "CommandPartCalculator", effect_seq_number: int) -> None:
        for move_data in self.data_by_effect[effect_seq_number].move_list:
            self.context.move_character_to(
                move_data.character_id, move_data.to_position
            )

    def _process_damage(self: "CommandPartCalculator", effect_seq_number: int) -> None:
        for damage_calc in list(
            self.data_by_effect[effect_seq_number].damage_data_list
        ):
            self._apply_buff_events(
                effect_seq_number,
                damage_calc.base.attacker_id,
                BuffCountDeductCondition.ON_ATTACK,
                damage_calc.base.target_id,
            )
            self._apply_buff_events(
                effect_seq_number,
                damage_calc.base.target_id,
                BuffCountDeductCondition.ON_HIT,  # noqa: F821
                damage_calc.base.attacker_id,
            )
        for damage_calc in self.data_by_effect[effect_seq_number].damage_data_list:
            attacker = self.context.characters[damage_calc.base.attacker_id]
            target = self.context.characters[damage_calc.base.target_id]

            is_magic_attack = (
                damage_calc.base.is_magic_attack
                if damage_calc.base.is_magic_attack is not None
                else attacker.status.is_magic_attacker
            )
            if is_magic_attack:
                damage_calc.modifiers.append(target.status.m_res)

            damage_calc.result_value = self.context.apply_damage(
                damage_calc.base.attacker_id,
                damage_calc.base.target_id,
                ValueWithModifiers(damage_calc.base.value, damage_calc.modifiers),
                self,
                effect_seq_number,
            )

    def _process_heal(self: "CommandPartCalculator", effect_seq_number: int) -> None:
        for heal_calc in list(self.data_by_effect[effect_seq_number].heal_data_list):
            self._apply_buff_events(
                effect_seq_number,
                heal_calc.base.healer_id,
                None,
                heal_calc.base.target_id,
            )
            self._apply_buff_events(
                effect_seq_number,
                heal_calc.base.target_id,
                None,
                heal_calc.base.healer_id,
            )
        for heal_calc in self.data_by_effect[effect_seq_number].heal_data_list:
            heal_calc.result_value = self.context.apply_heal(
                heal_calc.base.healer_id,
                heal_calc.base.target_id,
                ValueWithModifiers(heal_calc.base.value, heal_calc.modifiers),
                self,
                effect_seq_number,
            )

    def _process_buff_add(
        self: "CommandPartCalculator",
        effect_seq_number: int,
        phase: RoundPhaseType,
    ) -> None:
        buff_add_list = self.data_by_effect[effect_seq_number].buff_add_data_list
        if phase == RoundPhaseType.ALLY_ACTION:
            for data in buff_add_list:
                self.context.buff_container.add(data)
        elif phase == RoundPhaseType.ENEMY_PRE_ACTION:
            for data in buff_add_list:
                if data.add_timing == RoundPhaseType.ENEMY_PRE_ACTION:
                    self.context.buff_container.add(data)
        elif phase == RoundPhaseType.ENEMY_POST_ACTION:
            for data in buff_add_list:
                if data.add_timing == RoundPhaseType.ENEMY_POST_ACTION:
                    self.context.buff_container.add(data)
        else:
            raise ValueError(f"Cannot add buffs at this phase: {phase}")

    def _apply_buff_events(
        self: "CommandPartCalculator",
        effect_seq_number: int,
        char_id: CharacterId,
        deduct_condition: Optional[BuffCountDeductCondition],
        attacker_or_target: Optional[CharacterId] = None,
    ) -> None:
        buffs = self.context.buff_container.get_buffs_by(
            char_id, BuffApplyTiming.ON_ACTION
        )
        events = [buff.create_event() for buff in buffs]
        events.sort(key=lambda e: e.priority.value)
        for event in events:
            if event.is_applied(self.context, char_id, attacker_or_target):
                event.apply(char_id, attacker_or_target, self, effect_seq_number)

        if deduct_condition is not None:
            for buff in buffs:
                buff.duration.deduct_count(deduct_condition)
                if buff.duration.finished:
                    self.context.buff_container.remove(buff.uid)
