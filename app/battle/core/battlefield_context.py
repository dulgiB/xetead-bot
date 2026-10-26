import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Optional

from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet
from utils.battle_helpers import (
    columns_for_span,
    columns_overlap,
    is_reachable_between,
)
from utils.logging import print_apply_damage, print_apply_heal
from utils.name_matching import (
    normalize_name,
    resolve_matching_key,
    resolve_name_or_alias,
)

from battle.core.buff_container import BuffContainer
from battle.core.charm_aura_container import CharmAuraContainer, CharmBuff
from battle.core.field_effect_container import FieldEffectContainer
from battle.core.command_calculator import CommandPartCalculator
from battle.core.commands.models import (
    FIELD_EFFECT_REMOVED_RESULT,
    BattleLogEntry,
    BattleLogEntryKind,
    CommandPartProcessResult,
)
from battle.exceptions import (
    CommandValidationError,
    error_character_already_defeated,
    error_character_already_on_field,
    error_field_effect_not_found,
    error_not_a_field_effect,
    error_skill_not_registered,
    error_span_out_of_board,
    error_summon_column_full,
    error_summon_target_not_found,
    error_target_does_not_exist,
    error_too_many_characters,
)
from battle.objects.buff.models import BuffData
from battle.objects.character.combat_character import CombatCharacter
from battle.objects.character.combat_stats import CombatStats
from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    KEYWORD_BOOST_HP_COST,
    MAX_SKILL_SLOT_COUNT,
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
    ItemType,
)
from battle.objects.field_effect.models import FieldEffect, FieldEffectSource
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId, SummonData, ValueWithModifiers
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.passive_skill.passive_skill import PassiveSkillWrapperBuff
from battle.objects.skill.models import Skill, SkillData
from spreadsheets.inventory import Inventory

# 커맨드 문법에서 의미가 있는 기호(parser._NAME이 이름에서 빼는 것). 별명에
# 들어 있으면 파서가 이름을 거기서 끊어 그 별명으로는 지정할 수 없다.
_NAME_ALIAS_FORBIDDEN = re.compile(r"[/\[\]+\-\n]")


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
        # 소환할 수 있는 캐릭터 명단. 봇 계층이 "캐릭터"/"에너미" 시트 명단을
        # 넘긴다 — 명단은 멘션마다 다시 읽히므로 값이 아니라 읽는 함수로 받는다.
        # 기본값(빈 명단)인 전장에서는 소환이 항상 "찾을 수 없음"이 된다.
        self.summon_roster_source: Callable[
            [], Mapping[str, CombatCharacterDataFromSpreadsheet]
        ] = dict
        # 체력을 "?/?"로 가리는 캐릭터. 필드에서 빠져도 지우지 않는다 — 결투
        # 기권자의 피해 정산처럼 빠진 뒤에도 체력이 답글에 나가는 경로가 있다.
        self.hp_hidden_ids: set[CharacterId] = set()

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

        # 전장 전체에 걸린 효과. 캐릭터가 아니라 전장에 붙으며, 명시적으로
        # 해제하기 전까지 유지된다.
        self.field_effects: FieldEffectContainer = FieldEffectContainer(self)

        # 소지자 사거리 안에만 걸리는 부적 효과. 위치가 바뀔 때마다 대상을
        # 다시 계산해야 해서 배치·이동·퇴장 경로가 모두 refresh()를 부른다.
        self.charm_auras: CharmAuraContainer = CharmAuraContainer(self)

        self.results: list[CommandPartProcessResult] = []
        self.prev_round_results: list[CommandPartProcessResult] = []
        self.moved_this_round: set[CharacterId] = set()
        # 이번 라운드에 답글에서 효과 예고 줄을 이미 보여 준 스킬 id. 같은
        # 스킬을 여러 번 선언해도 설명이 반복되지 않게 한다.
        self.previewed_skill_ids: set[str] = set()
        self.damaged_this_round: set[CharacterId] = set()
        # 이번 라운드에 대미지가 실제로 적용된 (공격자, 대상) 조합.
        # results는 커맨드 하나가 끝나야 채워지므로, 같은 커맨드 안에서
        # "방금 때린 대상을 또 때렸는가"를 보려면 이 집합이 필요하다.
        self.attacked_this_round: set[tuple[CharacterId, CharacterId]] = set()
        # 직전 라운드의 damaged_this_round 스냅샷. 라운드 시작 시점에 "지난
        # 라운드에 누가 맞았는가"를 읽어야 하는 조건용이다 — 라운드 종료
        # 트리거로 버프를 걸면 같은 on_round_end()가 곧바로 턴을 차감해
        # 지속시간이 1턴 짧아지므로, 그런 패시브는 "라운드 시작 시 지난 라운드
        # 결과로 판정"하는 쪽으로 표현한다.
        self.prev_damaged_this_round: set[CharacterId] = set()

    def __str__(self):
        return self.format_field_text()

    def format_field_text(
        self,
        *,
        ally_label: str = FactionType.ALLY.value,
        enemy_label: str = FactionType.ENEMY.value,
        ally_first: bool = False,
        compact_columns: bool = False,
    ) -> str:
        """필드 위치 보드 + 버프/디버프 요약을 텍스트로 그린다(진행 중인
        전투 표시용). 전투가 끝난 시점처럼 버프/디버프 요약이 더 이상
        의미 없는 곳에는 이 메서드 대신 버프 요약이 아예 없는
        format_position_board()를 쓴다."""
        board = self.format_position_board(
            ally_label=ally_label,
            enemy_label=enemy_label,
            ally_first=ally_first,
            compact_columns=compact_columns,
        )
        status_summary = self.format_status_summary()
        return f"{board}\n\n{status_summary}" if status_summary else board

    def format_status_summary(self) -> str:
        """필드 효과 + 버프/디버프 요약. 걸린 것이 없으면 빈 문자열이다."""
        # 필드 효과를 버프 요약보다 먼저 둔다 — 캐릭터별 버프 중 일부가
        # 여기서 온 것이라, 무엇이 전장에 걸려 있는지를 먼저 보여야 읽힌다.
        blocks = [
            block
            for block in (
                self._format_field_effect_summary(),
                self._format_buff_summary(),
            )
            if block
        ]
        return "\n\n".join(blocks)

    def _format_field_effect_summary(self) -> str:
        """전장에 걸려 있는 필드 효과 목록. 걸린 것이 없으면 빈 문자열이다."""
        effects = self.field_effects.as_display_list()
        if not effects:
            return ""
        lines = ["**[필드 효과]**"]
        for effect in effects:
            lines.append(f"▸ {effect.display_label()}")
            if effect.description:
                lines.append(f" ↳ {effect.description}")
        return "\n".join(lines)

    def format_position_board(
        self,
        *,
        ally_label: str = FactionType.ALLY.value,
        enemy_label: str = FactionType.ENEMY.value,
        ally_first: bool = False,
        compact_columns: bool = False,
    ) -> str:
        """필드 위치 보드만 텍스트로 그린다(버프/디버프 요약 제외).
        position_map은 항상 FactionType 기준이라(대련의 SideType도
        PracticeBattlefieldContext 내부에서 FactionType으로 매핑되어
        들어온다) 헤더로 쓸 라벨만 갈아끼우면 대련처럼 "아군"/"적군" 대신
        "1팀"/"2팀" 등을 보여줄 수 있다.

        `ally_first`는 두 블록 중 어느 쪽을 먼저 그릴지만 바꾼다. 기본값
        False(적군 먼저)는 본 전투 필드 이미지와 같은 순서다.

        `compact_columns=True`면 아무도 없는 열은 아예 줄을 그리지 않는다
        — 본 전투는 필드 이미지가 따로 있어 7열 전체를 텍스트로도 보여줘야
        하지만, 대련/상시전투는 텍스트가 유일한 필드 표시 수단이면서도
        게시물 길이 제한(500자) 안에 버프 요약까지 넣어야 해서 빈 열까지
        다 그리면 길이가 금방 초과된다."""
        enemy_str = []
        for column_idx, enemies in self.position_map[FactionType.ENEMY].items():
            if compact_columns and not enemies:
                continue
            enemy_list: list[CombatCharacter | str] = []
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
            if compact_columns and not allies:
                continue
            ally_list: list[CombatCharacter | str] = []
            for i in range(CHARACTER_PER_COLUMN):
                if i in allies.keys():
                    ally_list.append(self.characters[allies[i]])
                else:
                    ally_list.append("-")

            ally_str.append(
                f"[{column_idx}] " + " | ".join(str(ally) for ally in ally_list)
            )

        enemy_block = (
            f"{enemy_label}\n{'\n'.join(enemy_str) if enemy_str else '(없음)'}"
        )
        ally_block = f"{ally_label}\n{'\n'.join(ally_str) if ally_str else '(없음)'}"
        return (
            f"{ally_block}\n\n{enemy_block}"
            if ally_first
            else f"{enemy_block}\n\n{ally_block}"
        )

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
                if isinstance(buff, CharmBuff):
                    description = buff.get_description(self)
                else:
                    buff_data = self._buff_dictionary.get(buff.id)
                    description = buff_data.description if buff_data is not None else ""
                stack_count = buff.stack_count if buff.max_stack is not None else None
                blocks.append(
                    f"{char_id.name} | [{buff.display_id_label()}]"
                    f"{buff.duration.display_text(stack_count)}\n"
                    f" ↳ {description}"
                )
        return "\n\n".join(blocks)

    def clear(self):
        self.charm_auras.clear()
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
        self.prev_round_results = []
        self.moved_this_round = set()
        self.damaged_this_round = set()
        self.prev_damaged_this_round = set()
        self.attacked_this_round = set()

    def add_character(
        self,
        data: CombatCharacterDataFromSpreadsheet,
        faction: FactionType,
        column_idx: BattlefieldColumnIndex,
    ):
        char_id = CharacterId(data.name)

        if char_id in self.characters:
            raise CommandValidationError(error_character_already_on_field(char_id))

        # curr_hp가 비어 있으면(None) CombatStats가 max_hp로 채우므로 "체력
        # 미기재"와 "체력 0"을 구분해서 후자만 막는다.
        if data.curr_hp is not None and data.curr_hp <= 0:
            raise CommandValidationError(error_character_already_defeated(char_id))

        skills = self._build_skills(data, char_id)

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
                data.revival_count,
            ),
            skills=skills,
            hide_hp=data.hide_hp,
            span=data.span,
            keyword_date=data.keyword_date,
            name_aliases=data.name_aliases,
        )

        if data.hide_hp:
            self.hp_hidden_ids.add(char_id)

        self._register_passive(char_id, data.passive_skill_id)

        occupied = columns_for_span(column_idx, character.span)
        if len(occupied) < character.span:
            raise CommandValidationError(
                error_span_out_of_board(column_idx, character.span)
            )

        maybe_empty_slot = self.try_find_empty_slot(
            faction, column_idx, span=character.span
        )

        if maybe_empty_slot is None:
            raise CommandValidationError(error_too_many_characters(column_idx))

        # 걸친 열 전부에 등록해야 열당 인원 제한과 열 광역기 판정이 덩치를
        # 그대로 반영한다.
        for column in occupied:
            self.position_map[faction][column][maybe_empty_slot] = char_id
        self.characters[char_id] = character

        # 전투 도중 참전한 캐릭터도 이미 걸린 필드 효과를 즉시 받는다.
        # 배치 단계에서는 아직 필드 효과가 없어 비용이 들지 않는다.
        self.field_effects.apply_to_newcomer(char_id)

        # 부적 효과는 다음 라운드 시작부터 건다(grant_round_buffs()).
        if self.allow_charms:
            self.charm_auras.register_holder(char_id)

    def resolve_summon_id(self, raw: CharacterId) -> CharacterId:
        """공백 차이와 별명을 감안해 소환 명단의 에너미 이름으로 맞춘다. 없으면 raw."""
        aliases_by_name = {
            name: data.name_aliases
            for name, data in self.summon_roster_source().items()
            if data.is_enemy
        }
        return CharacterId(resolve_name_or_alias(raw.name, aliases_by_name))

    def check_summon(self, summon: SummonData) -> CombatCharacterDataFromSpreadsheet:
        """소환할 수 있는지 확인하고 그 캐릭터의 시트 데이터를 돌려준다.
        안 되면 CommandValidationError를 낸다 — add_character()와 같은
        조건이지만, 자리가 없을 때의 문구만 소환에 맞게 바꾼다.

        시트 체력은 보지 않는다. 소환은 매번 새 개체를 들이는 것이라 최대
        체력으로 들어오고(summon_character()), 앞서 쓰러져 시트 체력이 0으로
        남은 소환물도 다시 부를 수 있어야 한다."""
        data = self.summon_roster_source().get(summon.character_id.name)
        if data is None or not data.is_enemy:
            raise CommandValidationError(
                error_summon_target_not_found(summon.character_id)
            )
        if summon.character_id in self.characters:
            raise CommandValidationError(
                error_character_already_on_field(summon.character_id)
            )
        if len(columns_for_span(summon.column, data.span)) < data.span:
            raise CommandValidationError(
                error_span_out_of_board(summon.column, data.span)
            )
        if (
            self.try_find_empty_slot(summon.faction, summon.column, span=data.span)
            is None
        ):
            raise CommandValidationError(error_summon_column_full(summon.column))
        return data

    def summon_character(self, summon: SummonData) -> CombatCharacter:
        data = self.check_summon(summon)
        self.add_character(
            replace(data, curr_hp=data.max_hp), summon.faction, summon.column
        )
        return self.characters[summon.character_id]

    def _build_skills(
        self, data: CombatCharacterDataFromSpreadsheet, char_id: CharacterId
    ) -> list[Skill]:
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
        return skills

    def _register_passive(self, char_id: CharacterId, passive_skill_id: str) -> None:
        if passive_skill_id and passive_skill_id in self._passive_skill_dictionary:
            wrappers = PassiveSkillWrapperBuff.create(
                char_id, self._passive_skill_dictionary[passive_skill_id]
            )
            for wrapper in wrappers:
                self.buff_container.add_passive_wrapper(wrapper)

    def uses_stacking_buffs(self, char_id: CharacterId) -> bool:
        """이 캐릭터의 스킬·패시브 중 적층형 버프/디버프(`max_stack`이 있는
        버프)를 부여하거나 참조하는 것이 하나라도 있는지.

        부여뿐 아니라 참조도 센다 — 다른 버프가 그 스택을 읽는 경우(스택 비례
        지속 대미지 등)까지 적층형 운용으로 보려면, 버프가 가리키는
        `reference_buff_id`를 따라가야 한다."""
        character = self.characters.get(char_id)
        if character is None:
            return False
        effects = [e for skill in character.skills for e in skill.data.effects]
        pending: list[str] = []
        for wrapper in self.passive_wrappers_of(char_id):
            passive = self._passive_skill_dictionary.get(wrapper.id)
            if passive is None:
                continue
            effects.extend(passive.effects)
            event_ref = getattr(passive.buff_mod_event, "reference_buff_id", None)
            if event_ref:
                pending.append(event_ref)
        for effect in effects:
            pending.extend(
                buff_id
                for buff_id in (
                    effect.buff_id,
                    effect.reference_buff_id,
                    effect.required_target_buff_id,
                )
                if buff_id
            )
        seen: set[str] = set()
        while pending:
            buff_id = pending.pop()
            if buff_id in seen:
                continue
            seen.add(buff_id)
            buff_data = self._buff_dictionary.get(buff_id)
            if buff_data is None:
                continue
            if buff_data.max_stack is not None:
                return True
            if buff_data.reference_buff_id:
                pending.append(buff_data.reference_buff_id)
        return False

    def passive_wrappers_of(
        self, char_id: CharacterId
    ) -> list[PassiveSkillWrapperBuff]:
        return [
            buff
            for buff in self.buff_container.get_buffs_by(char_id, None)
            if isinstance(buff, PassiveSkillWrapperBuff) and buff.given_by == char_id
        ]

    def refresh_character_data(
        self, char_id: CharacterId, data: CombatCharacterDataFromSpreadsheet
    ) -> None:
        """전장에 있는 캐릭터의 스탯·스킬·패시브를 시트에서 다시 읽은 값으로
        바꾼다(admin `[스테이터스 갱신]` 전용). 배치 때 한 번 복사해 두는 값들이라, 이
        경로 말고는 전투 도중 시트 수정이 전장에 들어오지 않는다.

        위치·진영·버프·남은 코스트는 그대로 두고, 현재 체력은 새 최대 체력을
        넘지 않게만 자른다(시트 체력을 들일지는 호출측이 정한다). `span`은
        바꾸지 않는다 — 점유 열이 달라지면 자리를 다시 잡아야 해서, 그건
        배치의 일이다.

        스킬/패시브 id가 이 전투 데이터에 없으면 아무것도 바꾸지 않고
        CommandValidationError를 낸다. 스킬 데이터는 [전투준비] 때 읽으므로
        그 뒤 시트에 새로 만든 스킬은 여기서 찾을 수 없다.
        """
        character = self.characters[char_id]
        for skill_id in data.skill_id_list[:MAX_SKILL_SLOT_COUNT]:
            if skill_id and skill_id not in self._skill_dictionary:
                raise CommandValidationError(error_skill_not_registered(skill_id))
        if (
            data.passive_skill_id
            and data.passive_skill_id not in self._passive_skill_dictionary
        ):
            raise CommandValidationError(
                error_skill_not_registered(data.passive_skill_id)
            )

        character.status.refresh_base(
            data.atk,
            data.max_hp,
            data.attack_range,
            data.m_res,
            data.is_magic_attacker,
            data.max_cost,
            data.revival_count,
        )
        character.status.curr_hp = min(
            character.status.curr_hp, character.status[CombatStatType.MAX_HP]
        )
        character.skills = self._build_skills(data, char_id)
        character.name_aliases = data.name_aliases
        character.hide_hp = data.hide_hp
        if data.hide_hp:
            self.hp_hidden_ids.add(char_id)
        else:
            self.hp_hidden_ids.discard(char_id)

        # 패시브는 id가 바뀐 경우에만 다시 건다 — 같은 패시브를 다시 걸면
        # 래퍼가 들고 있던 상태가 초기화된다. 옛 패시브가 이미 다른 캐릭터에게
        # 부여해 둔 버프는 남은 지속시간대로 둔다.
        old_wrappers = self.passive_wrappers_of(char_id)
        old_passive_ids = {wrapper.id for wrapper in old_wrappers}
        new_passive_ids = {data.passive_skill_id} if data.passive_skill_id else set()
        if old_passive_ids != new_passive_ids:
            for wrapper in old_wrappers:
                self.buff_container.remove(wrapper.uid)
            self._register_passive(char_id, data.passive_skill_id)

    def _remove_from_position_map(self, char_id: CharacterId) -> None:
        char = self.characters[char_id]
        removed = False
        for slots in self.position_map[char.faction].values():
            for slot_idx, cid in list(slots.items()):
                if cid == char_id:
                    slots.pop(slot_idx)
                    removed = True
        if not removed:
            raise CommandValidationError(error_target_does_not_exist(char_id))

    def remove_character(self, char_id: CharacterId) -> "CombatCharacter":
        if char_id not in self.characters:
            raise CommandValidationError(error_target_does_not_exist(char_id))

        for buff in self.buff_container.get_buffs_by(char_id, None):
            self.buff_container.remove(buff.uid)

        self.charm_auras.unregister_holder(char_id)
        self._remove_from_position_map(char_id)
        return self.characters.pop(char_id)

    def try_find_empty_slot(
        self,
        faction: FactionType,
        column: BattlefieldColumnIndex,
        span: int = 1,
        ignore: Optional[CharacterId] = None,
    ) -> Optional[int]:
        """`column`을 가장 왼쪽으로 삼아 span개 열에 모두 비어 있는 슬롯
        번호를 찾는다. 없으면 None.

        여러 열에 걸치는 캐릭터도 모든 열에서 같은 슬롯 번호를 쓴다 — 열마다
        다른 번호를 잡으면 제거·표시 쪽에서 같은 캐릭터를 열마다 다른 자리로
        보게 된다.

        `ignore`가 차지한 자리는 빈 것으로 센다 — 이동은 원래 자리를 비우고
        들어가므로, 자기 자신 때문에 자리가 없다고 판정하면 다열 캐릭터가
        한 칸도 움직이지 못한다(이동 전후 점유 열이 겹치기 때문).
        """
        columns = columns_for_span(column, span)
        if len(columns) < span:
            return None
        for i in range(CHARACTER_PER_COLUMN):
            if all(
                self.position_map[faction][col].get(i) in (None, ignore)
                for col in columns
            ):
                return i
        return None

    def resolve_character_id(self, raw: CharacterId) -> CharacterId:
        """공백 차이와 별명("name_alias")을 감안해 전장에 등록된 캐릭터를 찾는다.

        별명은 전장에 있는 캐릭터끼리만 견준다 — 필드 밖 캐릭터와 겹치는
        별명은 이 전투에서 문제가 되지 않는다. 일치하는 항목이 없거나 별명이
        둘 이상에게 걸리면 raw를 그대로 반환해, 호출측의 '존재하지 않음' 처리
        경로를 타게 한다.
        """
        if raw in self.characters:
            return raw
        matched_name = resolve_name_or_alias(
            raw.name,
            {cid.name: char.name_aliases for cid, char in self.characters.items()},
        )
        return CharacterId(matched_name)

    def name_alias_problems(self) -> list[str]:
        """전장에 있는 캐릭터의 별명 중 대상 지정에 쓸 수 없는 것을 설명한다.

        어느 것도 커맨드를 막지는 않는다 — 그 별명이 "찾을 수 없음"이 되거나
        다른 해석에 밀릴 뿐이라, [전투개시] 때 admin에게 알리는 데 쓴다.
        """
        problems: list[str] = []
        names = {normalize_name(cid.name): cid.name for cid in self.characters}
        # 정규화한 별명 → (처음 본 표기, 그 별명을 쓰는 캐릭터들)
        owners: dict[str, tuple[str, list[str]]] = {}
        for cid, character in self.characters.items():
            for alias in character.name_aliases:
                if _NAME_ALIAS_FORBIDDEN.search(alias):
                    problems.append(
                        f"{cid.name}의 별명 '{alias}'에 커맨드 기호(/ - + [ ])가 있어"
                        " 대상 지정에 쓸 수 없습니다."
                    )
                    continue
                key = normalize_name(alias)
                if (other := names.get(key)) is not None and other != cid.name:
                    problems.append(
                        f"{cid.name}의 별명 '{alias}'이(가) {other}의 이름과 같아"
                        f" {other}을(를) 가리킵니다."
                    )
                    continue
                try:
                    BattlefieldColumnIndex.from_str(alias)
                except ValueError:
                    pass
                else:
                    problems.append(
                        f"{cid.name}의 별명 '{alias}'은(는) 스킬 대상에서 열 번호로"
                        " 읽힙니다."
                    )
                _, alias_owners = owners.setdefault(key, (alias, []))
                if cid.name not in alias_owners:
                    alias_owners.append(cid.name)
        for shown, names_with_alias in owners.values():
            if len(names_with_alias) > 1:
                problems.append(
                    f"별명 '{shown}'을(를) {', '.join(names_with_alias)}이(가) 함께"
                    " 써서 이 별명으로는 아무도 지정되지 않습니다."
                )
        return problems

    def resolve_skill_id(self, user_id: CharacterId, raw_skill_id: str) -> str:
        """공백 차이를 무시하고 해당 캐릭터가 보유한 스킬 id를 찾는다."""
        user = self.characters.get(user_id)
        if user is None:
            return raw_skill_id
        return resolve_matching_key(raw_skill_id, (s.data.id for s in user.skills))

    def find_character_position(self, char_id: CharacterId) -> BattlefieldColumnIndex:
        if char_id not in self.characters.keys():
            raise CommandValidationError(error_target_does_not_exist(char_id))

        char = self.characters[char_id]
        for column_idx, characters in self.position_map[char.faction].items():
            if char_id in characters.values():
                return column_idx

        return BattlefieldColumnIndex.NONE

    def find_character_columns(
        self, char_id: CharacterId
    ) -> tuple[BattlefieldColumnIndex, ...]:
        """캐릭터가 차지하는 열 전부(왼쪽부터).

        사거리·"같은 열" 판정은 모두 이 목록을 기준으로 한다 — 위치 하나만
        보면 다열 에너미가 왼쪽 끝 열에서만 닿고 맞는 꼴이 된다."""
        char = self.characters.get(char_id)
        if char is None:
            return (BattlefieldColumnIndex.NONE,)
        return columns_for_span(self.find_character_position(char_id), char.span)

    def can_reach(
        self,
        ref_id: CharacterId,
        target_id: CharacterId,
        reachable_range: int,
    ) -> bool:
        """ref가 target에 닿는지(양쪽 모두 점유 열 전체 기준)."""
        return is_reachable_between(
            self.find_character_columns(ref_id),
            self.find_character_columns(target_id),
            reachable_range,
        )

    def shares_column(self, char_id: CharacterId, other_id: CharacterId) -> bool:
        """두 캐릭터가 한 열이라도 함께 차지하는지("같은 열" 판정)."""
        return columns_overlap(
            self.find_character_columns(char_id),
            self.find_character_columns(other_id),
        )

    def move_character_to(
        self, char_id: CharacterId, to_position: BattlefieldColumnIndex
    ):
        char = self.characters[char_id]
        occupied = columns_for_span(to_position, char.span)
        if len(occupied) < char.span:
            raise CommandValidationError(
                error_span_out_of_board(to_position, char.span)
            )

        empty_slot = self.try_find_empty_slot(
            char.faction, to_position, span=char.span, ignore=char_id
        )

        # 강제 이동(스킬 효과 등)은 is_valid를 거치지 않으므로 체크를 유지한다.
        if empty_slot is None:
            raise CommandValidationError(error_too_many_characters(to_position))

        self._remove_from_position_map(char_id)
        for column in occupied:
            self.position_map[char.faction][column][empty_slot] = char_id
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
        self.attacked_this_round.add((attacker_id, target_id))
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
        self.previewed_skill_ids = set()
        self.attacked_this_round = set()
        # 지우기 전에 스냅샷해 둬야 ON_ROUND_START 조건이 지난 라운드의
        # 피격 기록을 읽을 수 있다.
        self.prev_damaged_this_round = self.damaged_this_round
        self.damaged_this_round = set()
        # 부적 범위는 이 시점의 위치로 정한다. 코스트 회복보다 먼저여야 턴당
        # 코스트 보너스가 이번 라운드에 반영된다.
        if self.allow_charms:
            self.charm_auras.grant_round_buffs()
        # 코스트 회복이 ON_ROUND_START 버프보다 먼저여야 "다음 라운드 코스트
        # 감소" 버프가 덮어써지지 않는다.
        for character in self.characters.values():
            character.status.refill_cost_for_round()
        self.buff_container.on_round_start()

    def on_finish_round(self) -> tuple[list[BattleLogEntry], list[CharacterId]]:
        log_entries, _ = self.buff_container.on_round_end()
        # 버프의 라운드 종료 처리 뒤에 줄여야, 마지막 턴인 필드 효과의
        # "라운드 종료" 트리거도 한 번 발동하고 걷힌다.
        log_entries.extend(
            BattleLogEntry(
                target_name=effect.id,
                kind=BattleLogEntryKind.FIELD_EFFECT,
                result=FIELD_EFFECT_REMOVED_RESULT,
            )
            for effect in self.field_effects.tick_turns()
        )
        eliminated = self._remove_eliminated_characters()
        self.prev_round_results = copy.deepcopy(self.results)
        self.results = []
        return log_entries, eliminated

    def _remove_eliminated_characters(self) -> list[CharacterId]:
        """체력이 0 이하인 **적군** 캐릭터를 필드에서 제거한다. 라운드
        도중이 아니라 라운드 종료 시점에 한 번만 처리한다 — 도중에 즉시
        제거하면 같은 라운드 안에서 그 캐릭터를 참조하는 다른 효과(광역기의
        나머지 대상, 반응형 버프의 사거리/위치 조회 등)가 예기치 않게
        실패할 수 있다.

        **아군은 체력이 0이 되어도 이 자동 탈락 대상이 아니다** — admin이
        `[탈락/이름]`으로 명시적으로 제거하기 전까지는 계속 필드에 남아
        평소처럼 행동/피격당한다(부활 회복 등으로 다시 양수 체력이 될
        수도 있으므로). `force_remove_character()`가 그 명시적 제거
        경로다.
        """
        eliminated = [
            char_id for char_id in self.characters if self.is_eliminated(char_id)
        ]
        for char_id in eliminated:
            self.remove_character(char_id)
        return eliminated

    def is_eliminated(self, char_id: CharacterId) -> bool:
        """이번 라운드 종료 때 자동으로 필드에서 빠질 캐릭터인지. 체력 0인
        적은 라운드 종료까지 필드에 남지만 이미 쓰러진 것이다."""
        char = self.characters.get(char_id)
        return (
            char is not None
            and char.status.curr_hp <= 0
            and char.faction == FactionType.ENEMY
        )

    def force_remove_character(self, char_id: CharacterId) -> list[CharacterId]:
        """admin이 `[탈락/이름]`으로 명시적으로 캐릭터를 필드에서 제거한다.

        0 체력이어도 자동으로는 탈락하지 않는 아군을 admin이 직접 사망
        처리할 때 쓴다."""
        self.remove_character(char_id)
        return [char_id]

    def on_battle_start(self) -> None:
        self.buff_container.on_battle_start()

    def on_battle_end(self) -> list[BattleLogEntry]:
        return self.buff_container.on_battle_end()

    def get_buff_data_by_id(self, buff_id: str) -> BuffData:
        return self._buff_dictionary[buff_id]

    def resolve_buff_id(self, raw_buff_id: str) -> str:
        """공백 차이를 무시하고 "버프" 시트에 등록된 버프 id를 찾는다.

        일치하는 항목이 없으면 raw_buff_id를 그대로 반환해, 호출측의
        '존재하지 않음' 처리 경로를 타게 한다.
        """
        return resolve_matching_key(raw_buff_id, self._buff_dictionary.keys())

    def get_buff_data_by_id_or_none(self, buff_id: str) -> Optional[BuffData]:
        """ "버프" 시트에 없는 id면 None. 시트에 등록되지 않은 버프(패시브 래퍼
        등)를 섞어 순회하는 쪽에서 KeyError 대신 건너뛸 수 있게 한다."""
        return self._buff_dictionary.get(buff_id)

    def get_buff_instance(
        self,
        char_id: CharacterId,
        buff_id: str,
        given_by: Optional[CharacterId] = None,
    ):
        return self.buff_container.get_buff(char_id, buff_id, given_by=given_by)

    def get_buff_stack(self, char_id: CharacterId, buff_id: str) -> int:
        buff = self.buff_container.get_buff(char_id, buff_id)
        return buff.stack_count if buff is not None else 0

    def all_passive_skill_data(self) -> list[PassiveSkillData]:
        """이 전투가 들고 있는 "스킬_패시브" 시트 데이터 전체. 시트 설정
        검증(봇 계층)이 읽는다."""
        return list(self._passive_skill_dictionary.values())

    def get_passive_skill_data_by_id(
        self, passive_id: str
    ) -> Optional[PassiveSkillData]:
        return self._passive_skill_dictionary.get(passive_id)

    def get_skill_data_by_id(self, skill_id: str) -> SkillData:
        return self._skill_dictionary[skill_id]

    def mark_skill_revealed(self, skill_id: str) -> None:
        """이 전투 세션 안에서 즉시 스킬을 공개 상태로 전환한다(스프레드시트
        write-back은 호출측 bot 레이어 책임). 이미 공개된 스킬이면 아무 것도
        하지 않는다."""
        data = self._skill_dictionary[skill_id]
        if not data.revealed:
            self._skill_dictionary[skill_id] = replace(data, revealed=True)

    @property
    def allow_item_usage(self) -> bool:
        return True

    @property
    def allow_field_effects(self) -> bool:
        """이 전장에서 필드 효과를 쓸 수 있는지 여부."""
        return True

    @property
    def allow_charms(self) -> bool:
        return True

    def charm_items(self) -> list[ItemData]:
        return [
            item
            for item in self._item_dictionary.values()
            if item.item_type is ItemType.CHARM
        ]

    def add_field_effect(
        self,
        passive_skill_id: str,
        source: FieldEffectSource,
        source_detail: str = "",
        turns: Optional[int] = None,
    ) -> Optional[FieldEffect]:
        """필드 효과를 전장에 올린다. 이미 상시로 걸려 있거나 이 전장이 필드
        효과를 쓰지 않으면 None을 반환한다(재부여 규칙은
        FieldEffectContainer.add() 참고).

        passive_skill_id가 "스킬_패시브" 시트에 없거나 필드 범위 대상
        타입이 아니면 CommandValidationError를 낸다 — 캐릭터 패시브를 필드
        효과로 올리면 홀더 없는 전장에서 대상이 하나도 잡히지 않아 조용히
        아무 일도 일어나지 않기 때문에, 부르는 쪽에서 바로 알아야 한다.
        """
        if not self.allow_field_effects:
            return None

        data = self._passive_skill_dictionary.get(passive_skill_id)
        if data is None:
            raise CommandValidationError(error_field_effect_not_found(passive_skill_id))
        if not data.is_field_effect:
            raise CommandValidationError(
                error_not_a_field_effect(passive_skill_id, data.target_type.value)
            )

        return self.field_effects.add(data, source, source_detail, turns)

    def remove_field_effect(self, passive_skill_id: str) -> Optional[FieldEffect]:
        """필드 효과를 걷는다. 그 효과가 부여한 버프도 함께 회수된다.
        걸려 있지 않으면 None을 반환한다."""
        return self.field_effects.remove(passive_skill_id)

    @property
    def allow_keyword_boost(self) -> bool:
        """이 전장에서 키워드 보정("+" 접미사) 커맨드를 쓸 수 있는지 여부.

        키워드 보정은 체력 20을 실제로 소모하고 "이번 진행에 사용함"을 캐릭터
        시트에 영구 기록하는, 되돌릴 수 없는 자원 소비다. 대련은 체력이
        절반인 임시 캐릭터로 진행하고 체력 변동을 시트에 반영하지도 않으므로
        그런 소비를 걸 수 없다(PracticeBattlefieldContext 참고).
        """
        return True

    def keyword_cost_hp(self, character: CombatCharacter) -> int:
        """키워드 보정 체력 대가를 낼 체력. 사용 가능 여부 검증에 쓴다."""
        return character.status.curr_hp

    def pay_keyword_cost_hp(self, character: CombatCharacter) -> tuple[int, int, bool]:
        """키워드 보정 체력 대가를 실제로 차감하고
        (차감 후 체력, 최대 체력, 그 체력이 시트의 실제 체력인지)를 반환한다.

        결투는 임시 체력이 아니라 시트의 실제 체력에서 빼야 해서
        (PracticeBattlefieldContext) 차감 대상 자체가 전장마다 다르다.
        """
        character.status.curr_hp -= KEYWORD_BOOST_HP_COST
        return (
            character.status.curr_hp,
            character.status[CombatStatType.MAX_HP],
            False,
        )

    def has_item(self, item_id: str) -> bool:
        return item_id in self._item_dictionary

    def get_item_data_by_id(self, item_id: str) -> ItemData:
        return self._item_dictionary[item_id]

    def resolve_item_id(self, raw_item_id: str) -> str:
        """공백 차이를 무시하고 등록된 아이템 id를 찾는다.

        일치하는 항목이 없으면 raw_item_id를 그대로 반환해, 호출측의
        '존재하지 않음' 처리 경로를 타게 한다.
        """
        return resolve_matching_key(raw_item_id, self._item_dictionary.keys())
