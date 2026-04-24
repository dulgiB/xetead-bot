import copy
from typing import Optional

from battle.core.buff_container import BuffContainer
from battle.core.commands.models import CommandProcessResult
from battle.exceptions import (
    CommandValidationError,
    error_target_does_not_exist,
    error_too_many_characters,
)
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.character.combat_character import CombatCharacter
from battle.objects.character.combat_stats import CombatStats
from battle.objects.define import BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId, ValueWithModifiers
from battle.objects.skill.models import SkillData
from spreadsheets.models.battle import CharacterDataFromSpreadsheet

CHARACTER_PER_COLUMN = 3


class BattlefieldContext:
    def __init__(
        self, buff_dict: dict[str, BuffData], skill_dict: dict[str, SkillData]
    ):
        self._buff_dictionary: dict[str, BuffData] = buff_dict
        self._skill_dictionary: dict[str, SkillData] = skill_dict

        self.characters: dict[CharacterId, CombatCharacter] = {}

        self.position_map: dict[
            FactionType, dict[BattlefieldColumnIndex, dict[int, CharacterId]]
        ] = {
            FactionType.ALLY: {
                index: {}
                for index in BattlefieldColumnIndex
                if index != BattlefieldColumnIndex.NONE
            },
            FactionType.ENEMY: {
                index: {}
                for index in BattlefieldColumnIndex
                if index != BattlefieldColumnIndex.NONE
            },
        }

        self.buff_container: BuffContainer = BuffContainer(self)

        self.results: list[CommandProcessResult] = []
        self.prev_round_results: list[CommandProcessResult] = []

    def __str__(self):
        enemy_str = []
        for column_idx, enemies in self.position_map[FactionType.ENEMY].items():
            enemy_list = []
            for i in range(CHARACTER_PER_COLUMN):
                if i in enemies.keys():
                    enemy_list.append(self.characters[enemies[i]])
                else:
                    enemy_list.append("-")

            enemy_str.append(
                f"[{column_idx}] " + " | ".join(str(enemy) for enemy in enemy_list)
            )

        ally_str = []
        for column_idx, allies in self.position_map[FactionType.ALLY].items():
            ally_list = []
            for i in range(CHARACTER_PER_COLUMN):
                if i in allies.keys():
                    ally_list.append(self.characters[allies[i]])
                else:
                    ally_list.append("-")

            ally_str.append(
                f"[{column_idx}] " + " | ".join(str(ally) for ally in ally_list)
            )

        return f"적군\n{'\n'.join(enemy_str)}\n\n아군\n{'\n'.join(ally_str)}"

    def clear(self):
        self.characters.clear()
        self.buff_container.clear()
        self.position_map[FactionType.ALLY] = {
            index: {}
            for index in BattlefieldColumnIndex
            if index != BattlefieldColumnIndex.NONE
        }
        self.position_map[FactionType.ENEMY] = {
            index: {}
            for index in BattlefieldColumnIndex
            if index != BattlefieldColumnIndex.NONE
        }

    def add_character(
        self,
        name: str,
        data: CharacterDataFromSpreadsheet,
        faction: FactionType,
        column_idx: BattlefieldColumnIndex,
    ):
        char_id = CharacterId(name)
        character = CombatCharacter(
            self,
            char_id,
            faction,
            CombatStats(
                data.atk,
                data.max_hp,
                data.attack_range,
                data.m_res,
                data.is_magic_attacker,
                data.max_cost,
                data.curr_hp if data.curr_hp else None,
            ),
            skill_1=self._skill_dictionary[data.skill_1_id].to_skill_instance(
                self, char_id
            ),
            skill_2=self._skill_dictionary[data.skill_2_id].to_skill_instance(
                self, char_id
            ),
        )

        passive_buff_add_data = BuffAddData(char_id, char_id, data.passive_buff_id)
        self.buff_container.add(passive_buff_add_data)

        maybe_empty_slot = self.try_find_empty_slot(faction, column_idx)

        if maybe_empty_slot is None:
            raise CommandValidationError(error_too_many_characters(column_idx))

        self.position_map[faction][column_idx][maybe_empty_slot] = char_id
        self.characters[char_id] = character

    def remove_character(self, char_id: CharacterId) -> "CombatCharacter":
        if char_id not in self.characters.keys():
            raise CommandValidationError(error_target_does_not_exist(char_id))

        char_pos = self.find_character_position(char_id)
        char = self.characters.pop(char_id)

        for slot_idx, character in self.position_map[char.faction][char_pos].items():
            if character == char.id:
                self.position_map[char.faction][char_pos].pop(slot_idx)
                break

        return char

    def try_find_empty_slot(
        self, faction: FactionType, column: BattlefieldColumnIndex
    ) -> Optional[int]:
        for i in range(CHARACTER_PER_COLUMN):
            if i not in self.position_map[faction][column].keys():
                return i
        return None

    def find_character_position(self, char_id: CharacterId) -> BattlefieldColumnIndex:
        if char_id not in self.characters.keys():
            raise ValueError(error_target_does_not_exist(char_id))

        char = self.characters[char_id]
        for column_idx, characters in self.position_map[char.faction].items():
            if char_id in characters.values():
                return column_idx

        return BattlefieldColumnIndex.NONE

    def move_character_to(
        self, char_id: CharacterId, to_position: BattlefieldColumnIndex
    ):
        char = self.characters[char_id]
        if empty_slot := self.try_find_empty_slot(char.faction, to_position):
            char_pos = self.find_character_position(char_id)
            for slot_idx, character in self.position_map[char.faction][
                char_pos
            ].items():
                if character == char.id:
                    self.position_map[char.faction][char_pos].pop(slot_idx)
                    break
            self.position_map[char.faction][to_position][empty_slot] = char_id

        else:
            raise CommandValidationError(error_too_many_characters(to_position))

    def apply_damage(
        self,
        attacker_id: CharacterId,
        target_id: CharacterId,
        damage_value: ValueWithModifiers,
    ):
        target = self.characters[target_id]
        final_value = damage_value.get_value(self, attacker_id, target_id)
        target.status.curr_hp -= final_value

        if damage_value.roll_result:
            roll_result_str = "+".join(
                str(roll) for roll in damage_value.roll_result.rolls
            )
            print(
                f"[apply_damage] {attacker_id} > {target_id} | ({roll_result_str}) → -{final_value}"
            )
        else:
            print(f"[apply_damage] {attacker_id} > {target_id} | -{final_value}")

    def apply_heal(
        self,
        healer_id: CharacterId,
        target_id: CharacterId,
        heal_value: ValueWithModifiers,
    ):
        target = self.characters[target_id]
        final_value = heal_value.get_value(self, healer_id, target_id)
        target.status.curr_hp += final_value
        print(f"[apply_heal] {healer_id} > {target_id} (+{final_value})")

    def on_finish_turn(self, char_id: CharacterId):
        pass

    def on_finish_round(self):
        self.prev_round_results = copy.deepcopy(self.results)
        self.results = []

    def get_buff_data_by_id(self, buff_name: str) -> BuffData:
        return self._buff_dictionary[buff_name]

    def get_skill_data_by_id(self, skill_name: str) -> SkillData:
        return self._skill_dictionary[skill_name]
