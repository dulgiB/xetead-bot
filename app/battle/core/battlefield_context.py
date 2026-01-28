from battle.exceptions import (
    CommandValidationError,
    error_target_does_not_exist,
    error_too_many_characters,
)
from battle.objects.character.combat_character import CombatCharacter
from battle.objects.define import BattlefieldSlotIndex, FactionType
from battle.objects.models import CharacterId, ValueWithModifiers


class BattlefieldContext:
    def __init__(self):
        self.characters: dict[CharacterId, CombatCharacter] = {}

        self.position_map: dict[
            FactionType, dict[BattlefieldSlotIndex, set[CharacterId]]
        ] = {
            FactionType.ALLY: {
                index: set[CharacterId]()
                for index in BattlefieldSlotIndex
                if index != BattlefieldSlotIndex.NONE
            },
            FactionType.ENEMY: {
                index: set[CharacterId]()
                for index in BattlefieldSlotIndex
                if index != BattlefieldSlotIndex.NONE
            },
        }

        self.results: list[CommandProcessResult] = []
        self.prev_round_results: list[CommandProcessResult] = []

    def __str__(self):
        enemy_str = []
        for slot_idx, enemy_ids in self.position_map[FactionType.ENEMY].items():
            if len(enemy_ids) == 0:
                enemy_str.append(f"[{slot_idx}] -")
            else:
                enemy_list = [self.characters[enemy_id] for enemy_id in enemy_ids]
                enemy_str.append(
                    f"[{slot_idx}] " + " | ".join(str(enemy) for enemy in enemy_list)
                )

        ally_str = []
        for slot_idx, ally_ids in self.position_map[FactionType.ALLY].items():
            if len(ally_ids) == 0:
                ally_str.append(str(slot_idx) + " -")
            else:
                ally_list = [self.characters[ally_id] for ally_id in ally_ids]
                ally_str.append(
                    f"[{slot_idx}] " + " | ".join(str(ally) for ally in ally_list)
                )

        return f"적군\n{'\n'.join(enemy_str)}\n\n아군\n{'\n'.join(ally_str)}"

    def clear(self):
        self.characters.clear()
        self.buff_container.clear()
        self.position_map[FactionType.ALLY] = {
            index: set[CharacterId]()
            for index in BattlefieldSlotIndex
            if index != BattlefieldSlotIndex.NONE
        }
        self.position_map[FactionType.ENEMY] = {
            index: set[CharacterId]()
            for index in BattlefieldSlotIndex
            if index != BattlefieldSlotIndex.NONE
        }

    def add_character(self, character: CombatCharacter, slot_idx: BattlefieldSlotIndex):
        char_id = character.id

        if len(self.position_map[character.faction][slot_idx]) >= 2:
            raise CommandValidationError(error_too_many_characters(slot_idx))

        self.position_map[character.faction][slot_idx].add(char_id)
        self.characters[char_id] = character

    def remove_character(self, char_id: CharacterId) -> "CombatCharacter":
        if char_id not in self.characters.keys():
            raise CommandValidationError(error_target_does_not_exist(char_id))

        char_pos = self.find_character_position(char_id)
        char = self.characters.pop(char_id)
        self.position_map[char.faction][char_pos].remove(char_id)
        return char

    def find_character_position(self, char_id: CharacterId) -> BattlefieldSlotIndex:
        if char_id not in self.characters.keys():
            raise ValueError(error_target_does_not_exist(char_id))

        char = self.characters[char_id]
        for slot_index, characters in self.position_map[char.faction].items():
            if char_id in characters:
                return slot_index

        return BattlefieldSlotIndex.NONE

    def move_character_to(
        self, char_id: CharacterId, to_position: BattlefieldSlotIndex
    ):
        char = self.characters[char_id]
        char_pos = self.find_character_position(char_id)
        self.position_map[char.faction][char_pos].remove(char_id)
        self.position_map[char.faction][to_position].add(char_id)

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

