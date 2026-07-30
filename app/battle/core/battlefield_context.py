import copy
import math
from typing import Optional

from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet
from utils.logging import print_apply_damage, print_apply_heal
from utils.name_matching import resolve_matching_key

from battle.core.buff_container import BuffContainer
from battle.core.command_calculator import CommandPartCalculator
from battle.core.commands.models import BattleLogEntry, CommandPartProcessResult
from battle.exceptions import (
    CommandValidationError,
    error_character_already_defeated,
    error_target_does_not_exist,
    error_too_many_characters,
)
from battle.objects.buff.buffs import BuffCompanionGuardian
from battle.objects.buff.models import BuffData
from battle.objects.character.combat_character import CombatCharacter
from battle.objects.character.combat_stats import CombatStats
from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    MAX_SKILL_SLOT_COUNT,
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
    MagicResistanceType,
)
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId, ValueWithModifiers
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.passive_skill.passive_skill import PassiveSkillWrapperBuff
from battle.objects.skill.models import SkillData
from spreadsheets.inventory import Inventory


class BattlefieldContext:
    def __init__(
        self,
        buff_dict: dict[str, BuffData],
        skill_dict: dict[str, SkillData],
        passive_skill_dict: "dict[str, PassiveSkillData] | None" = None,
        item_dict: "dict[str, ItemData] | None" = None,
        inventory: "Inventory | None" = None,
        *,
        milestone_n: int = 1,
    ):
        self._buff_dictionary: dict[str, BuffData] = buff_dict
        self._skill_dictionary: dict[str, SkillData] = skill_dict
        self._passive_skill_dictionary: dict[str, PassiveSkillData] = (
            passive_skill_dict or {}
        )
        self._item_dictionary: dict[str, ItemData] = item_dict or {}
        self.inventory: Inventory = inventory or Inventory({})
        self.milestone_n: int = milestone_n

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

        # 슬롯(position_map)을 차지하지 않는 동료 캐릭터: companion_id -> owner_id.
        # 이런 캐릭터는 self.characters에는 있지만 position_map에는 등록되지
        # 않으며, find_character_position()이 owner의 위치를 그대로 반환한다.
        self.companion_owners: dict[CharacterId, CharacterId] = {}

        self.results: list[CommandPartProcessResult] = []
        self.prev_round_results: list[CommandPartProcessResult] = []
        self.moved_this_round: set[CharacterId] = set()
        self.damaged_this_round: set[CharacterId] = set()

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

        board = f"적군\n{'\n'.join(enemy_str)}\n\n아군\n{'\n'.join(ally_str)}"

        buff_summary = self._format_buff_summary()
        if not buff_summary:
            return board
        return f"{board}\n\n{buff_summary}"

    def _format_buff_summary(self) -> str:
        """전장에 살아있는 캐릭터들이 보유한 버프/디버프를 텍스트로 나열한다.

        필드를 이미지로 보여줄 수 없는 경우(대련/상시전투, 또는 본 전투의
        이미지 캡처 실패 폴백)에는 버프/디버프 내용이 이미지 없이는 확인할
        방법이 없으므로, str(context)에 이 안내를 포함시킨다. 패시브 스킬
        래퍼(PassiveSkillWrapperBuff)는 "버프" 시트에 등록된 실제 버프가
        아니라 캐릭터 고유 특성이므로 이 목록에서는 제외한다.
        """
        blocks = []
        for char_id in self.characters:
            buffs = sorted(
                (
                    buff
                    for buff in self.buff_container.get_buffs_by(char_id, None)
                    if not isinstance(buff, PassiveSkillWrapperBuff)
                ),
                key=lambda buff: buff.id,
            )
            for buff in buffs:
                buff_data = self._buff_dictionary.get(buff.id)
                description = buff_data.description if buff_data is not None else ""
                stack_count = buff.stack_count if buff.max_stack is not None else None
                blocks.append(
                    f"{char_id.name} | [{buff.display_id_label()}]"
                    f"{buff.duration.display_text(stack_count)}"
                    f"{self._format_companion_hp_suffix(buff, char_id)}\n"
                    f"↳ {description}"
                )
        return "\n\n".join(blocks)

    def _format_companion_hp_suffix(self, buff, char_id: CharacterId) -> str:
        """BuffCompanionGuardian(CompanionBuff1)에 한해 동료 체력을 버프 표시줄에
        덧붙인다: " (동료이름: 현재/최대)". 동료가 아직 없으면 아무것도
        붙이지 않는다."""
        if not isinstance(buff, BuffCompanionGuardian):
            return ""
        companion = self.characters.get(self.find_companion_id(char_id))
        if companion is None:
            return ""
        max_hp = companion.status[CombatStatType.MAX_HP]
        return f" ({companion.id.name}: {companion.status.curr_hp}/{max_hp})"

    def clear(self):
        self.characters.clear()
        self.buff_container.clear()
        self.companion_owners.clear()
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
        self.prev_round_results = []
        self.moved_this_round = set()
        self.damaged_this_round = set()

    def add_character(
        self,
        data: CombatCharacterDataFromSpreadsheet,
        faction: FactionType,
        column_idx: BattlefieldColumnIndex,
    ):
        char_id = CharacterId(data.name)

        # curr_hp가 비어 있으면(None) CombatStats가 max_hp로 채우므로 "체력
        # 미기재"와 "체력 0"을 구분해서 후자만 막는다.
        if data.curr_hp is not None and data.curr_hp <= 0:
            raise CommandValidationError(error_character_already_defeated(char_id))

        skills = []
        for i in range(MAX_SKILL_SLOT_COUNT):
            if len(data.skill_id_list) <= i:
                break
            if data.skill_id_list[i]:
                skills.append(
                    self._skill_dictionary[data.skill_id_list[i]].to_skill_instance(
                        self, char_id
                    )
                )

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
                data.curr_hp,
            ),
            skills=skills,
        )

        if (
            data.passive_skill_id
            and data.passive_skill_id in self._passive_skill_dictionary
        ):
            wrappers = PassiveSkillWrapperBuff.create(
                char_id, self._passive_skill_dictionary[data.passive_skill_id]
            )
            for wrapper in wrappers:
                self.buff_container.add_passive_wrapper(wrapper)

        maybe_empty_slot = self.try_find_empty_slot(faction, column_idx)

        if maybe_empty_slot is None:
            raise CommandValidationError(error_too_many_characters(column_idx))

        self.position_map[faction][column_idx][maybe_empty_slot] = char_id
        self.characters[char_id] = character

    def _remove_from_position_map(self, char_id: CharacterId) -> None:
        char = self.characters[char_id]
        char_pos = self.find_character_position(char_id)
        for slot_idx, cid in self.position_map[char.faction][char_pos].items():
            if cid == char_id:
                self.position_map[char.faction][char_pos].pop(slot_idx)
                return
        raise CommandValidationError(error_target_does_not_exist(char_id))

    def remove_character(self, char_id: CharacterId) -> "CombatCharacter":
        if char_id not in self.characters:
            raise CommandValidationError(error_target_does_not_exist(char_id))

        for buff in self.buff_container.get_buffs_by(char_id, None):
            self.buff_container.remove(buff.uid)

        # 슬롯을 차지하지 않는 동료는 애초에 position_map에 없으므로 제거 시도를
        # 건너뛴다.
        if char_id not in self.companion_owners:
            self._remove_from_position_map(char_id)
        self.companion_owners.pop(char_id, None)
        return self.characters.pop(char_id)

    def try_find_empty_slot(
        self, faction: FactionType, column: BattlefieldColumnIndex
    ) -> Optional[int]:
        for i in range(CHARACTER_PER_COLUMN):
            if i not in self.position_map[faction][column].keys():
                return i
        return None

    def resolve_character_id(self, raw: CharacterId) -> CharacterId:
        """공백 차이를 무시하고 전장에 등록된 캐릭터를 찾는다.

        일치하는 항목이 없으면 raw를 그대로 반환한다 (호출측의 기존
        '존재하지 않음' 처리 경로를 그대로 타도록 하기 위함).
        """
        if raw in self.characters:
            return raw
        matched_name = resolve_matching_key(
            raw.name, (cid.name for cid in self.characters)
        )
        return CharacterId(matched_name)

    def resolve_skill_id(self, user_id: CharacterId, raw_skill_id: str) -> str:
        """공백 차이를 무시하고 해당 캐릭터가 보유한 스킬 id를 찾는다."""
        user = self.characters.get(user_id)
        if user is None:
            return raw_skill_id
        return resolve_matching_key(raw_skill_id, (s.data.id for s in user.skills))

    def find_companion_id(self, owner_id: CharacterId) -> Optional[CharacterId]:
        """owner_id가 소환한 동료의 CharacterId. 아직 한 번도 소환된 적 없다면
        None. 동료의 id는 최초 소환 시 결정된 이름을 그대로 쓰므로(죽어서
        curr_hp가 0이 되어도 companion_owners 등록은 유지된다), 공식으로
        재계산하지 않고 이 조회로 찾는다."""
        for companion_id, owner in self.companion_owners.items():
            if owner == owner_id:
                return companion_id
        return None

    def find_character_position(self, char_id: CharacterId) -> BattlefieldColumnIndex:
        if char_id not in self.characters.keys():
            raise CommandValidationError(error_target_does_not_exist(char_id))

        # 슬롯을 차지하지 않는 동료는 position_map을 뒤지지 않고 owner의 위치를
        # 그대로 따른다 — owner가 이동하면 동료도 자동으로 같이 이동한 것으로
        # 취급된다.
        owner_id = self.companion_owners.get(char_id)
        if owner_id is not None:
            return self.find_character_position(owner_id)

        char = self.characters[char_id]
        for column_idx, characters in self.position_map[char.faction].items():
            if char_id in characters.values():
                return column_idx

        return BattlefieldColumnIndex.NONE

    def move_character_to(
        self, char_id: CharacterId, to_position: BattlefieldColumnIndex
    ):
        char = self.characters[char_id]
        empty_slot = self.try_find_empty_slot(char.faction, to_position)

        # is_valid에서 사전 검증되었으므로 None 케이스는 발생하지 않는다.
        # 단, 버프에 의한 강제 이동(스킬 효과 등)은 is_valid를 거치지 않으므로
        # 방어적으로 체크를 유지한다.
        if empty_slot is None:
            raise CommandValidationError(error_too_many_characters(to_position))

        self._remove_from_position_map(char_id)
        self.position_map[char.faction][to_position][empty_slot] = char_id
        self.moved_this_round.add(char_id)

    def apply_damage(
        self,
        attacker_id: CharacterId,
        target_id: CharacterId,
        damage_value: ValueWithModifiers,
        calculator: Optional[CommandPartCalculator],
        effect_seq_number: int,
    ) -> int:
        target = self.characters[target_id]
        final_value = damage_value.get_value(
            calculator, attacker_id, target_id, effect_seq_number
        )
        target.status.curr_hp = max(0, target.status.curr_hp - final_value)
        print_apply_damage(attacker_id, target_id, damage_value, final_value)
        return final_value

    def apply_heal(
        self,
        healer_id: CharacterId,
        target_id: CharacterId,
        heal_value: ValueWithModifiers,
        calculator: Optional[CommandPartCalculator],
        effect_seq_number: int,
    ) -> int:
        target = self.characters[target_id]
        final_value = heal_value.get_value(
            calculator, healer_id, target_id, effect_seq_number
        )
        target.status.curr_hp = min(
            target.status[CombatStatType.MAX_HP], target.status.curr_hp + final_value
        )
        print_apply_heal(healer_id, target_id, heal_value, final_value)
        return final_value

    def on_start_round(self):
        self.moved_this_round = set()
        self.damaged_this_round = set()
        self.buff_container.on_round_start()
        for character in self.characters.values():
            character.status.remaining_cost = character.status[
                CombatStatType.COST_PER_TURN
            ]

    def on_finish_round(self) -> tuple[list[BattleLogEntry], list[CharacterId]]:
        log_entries, _ = self.buff_container.on_round_end()
        eliminated = self._remove_eliminated_characters()
        self.prev_round_results = copy.deepcopy(self.results)
        self.results = []
        return log_entries, eliminated

    def _remove_eliminated_characters(self) -> list[CharacterId]:
        """체력이 0 이하인 캐릭터를 필드에서 제거한다. 라운드 도중이 아니라
        라운드 종료 시점에 한 번만 처리한다 — 도중에 즉시 제거하면 같은
        라운드 안에서 그 캐릭터를 참조하는 다른 효과(광역기의 나머지 대상,
        반응형 버프의 사거리/위치 조회 등)가 예기치 않게 실패할 수 있다.
        그동안 체력 0인 캐릭터는 지금처럼 필드에 남아 있는 채로 정상 처리된다.

        슬롯을 차지하지 않는 동료(및 동료를 보유한 캐릭터)는 제외한다 —
        동료는 죽어도(curr_hp=0) companion_owners 등록을 유지한 채 남아
        있다가 나중에 revive_companion()으로 재소환되는 별도 생애주기를
        가지므로, remove_character()로 지우면 이 생애주기가 깨진다."""
        eliminated = [
            char_id
            for char_id, char in self.characters.items()
            if char.status.curr_hp <= 0
            and char_id not in self.companion_owners
            and self.find_companion_id(char_id) is None
        ]
        for char_id in eliminated:
            self.remove_character(char_id)
        return eliminated

    def on_battle_start(self) -> None:
        self.buff_container.on_battle_start()

    def on_battle_end(self) -> None:
        self.buff_container.on_battle_end()

    def _spawn_companion_character(
        self, owner: CombatCharacter, companion_id: CharacterId, hp_percent: int
    ) -> None:
        """일반 캐릭터와 달리 position_map 슬롯을 전혀 차지하지 않는다(진영당
        열 3자리를 두고 아군과 경쟁하지 않는다) — companion_owners에 등록해
        find_character_position()이 owner의 위치를 그대로 따르게 한다. 그래서
        add_character()를 거치지 않고 CombatCharacter를 직접 만든다."""
        companion_max_hp = math.floor(
            owner.status[CombatStatType.MAX_HP] * hp_percent / 100
        )
        character = CombatCharacter(
            self,
            companion_id,
            owner.faction,
            CombatStats(
                0,
                companion_max_hp,
                0,
                MagicResistanceType.NORMAL,
                False,
                0,
                None,
            ),
            skills=[],
        )
        self.characters[companion_id] = character
        self.companion_owners[companion_id] = owner.id

    def spawn_companion_if_absent(
        self, owner_id: CharacterId, buff_name: str, hp_percent: int
    ) -> None:
        """owner_id의 소환수 성격의 동료를 처음 소환한다. 이미 살아 있으면
        (존재 + 체력 1 이상) 아무 일도 하지 않는다 — 전투 시작 시 패시브가
        중복 호출돼도 안전한 idempotent 헬퍼다.

        동료의 CharacterId는 이 시점에 buff_name(owner에게 부여되는 가디언
        버프의 id) 그대로 확정된다 — 가디언 버프 id는 해당 캐릭터 전용으로
        유일하다는 전제이므로 owner 이름을 덧붙이지 않는다. 이후 재소환
        (revive_companion)이나 조회(find_companion_id)는 이 이름을 다시
        계산하지 않고 companion_owners 등록을 그대로 재사용한다.
        """
        existing_id = self.find_companion_id(owner_id)
        if existing_id is not None:
            existing = self.characters[existing_id]
            if existing.status.curr_hp > 0:
                return

        owner = self.characters.get(owner_id)
        if owner is None:
            return

        companion_id = existing_id or CharacterId(buff_name)
        self._spawn_companion_character(owner, companion_id, hp_percent)

    def revive_companion(self, owner_id: CharacterId, hp_percent: int) -> None:
        """owner_id가 전투 중 최초 소환한 적 있는(companion_owners에 등록된)
        동료를 낮은 체력으로 재소환한다. 패시브(spawn_companion_if_absent)가
        전투 시작 시 항상 먼저 동료를 소환해 이름을 확정해 두므로, 재소환
        스킬 효과는 그 이름을 다시 알 필요 없이 이 메서드로 위임한다."""
        companion_id = self.find_companion_id(owner_id)
        if companion_id is None:
            raise ValueError(f"{owner_id.name}의 동료가 아직 한 번도 소환되지 않았습니다.")

        owner = self.characters.get(owner_id)
        if owner is None:
            return

        self._spawn_companion_character(owner, companion_id, hp_percent)

    def get_buff_data_by_id(self, buff_id: str) -> BuffData:
        return self._buff_dictionary[buff_id]

    def get_buff_instance(self, char_id: CharacterId, buff_id: str):
        return self.buff_container.get_buff(char_id, buff_id)

    def get_buff_stack(self, char_id: CharacterId, buff_id: str) -> int:
        buff = self.buff_container.get_buff(char_id, buff_id)
        return buff.stack_count if buff is not None else 0

    def get_skill_data_by_id(self, skill_id: str) -> SkillData:
        return self._skill_dictionary[skill_id]

    @property
    def allow_item_usage(self) -> bool:
        """이 전장에서 아이템 커맨드를 사용할 수 있는지 여부."""
        return True

    def has_item(self, item_id: str) -> bool:
        return item_id in self._item_dictionary

    def get_item_data_by_id(self, item_id: str) -> ItemData:
        return self._item_dictionary[item_id]

    def resolve_item_id(self, raw_item_id: str) -> str:
        """공백 차이를 무시하고 등록된 아이템 id를 찾는다.

        일치하는 항목이 없으면 raw_item_id를 그대로 반환한다 (호출측의
        기존 '존재하지 않음' 처리 경로를 그대로 타도록 하기 위함).
        """
        return resolve_matching_key(raw_item_id, self._item_dictionary.keys())
