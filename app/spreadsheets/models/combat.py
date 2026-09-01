from dataclasses import dataclass
from typing import Optional

from battle.objects.define import MAX_SKILL_SLOT_COUNT, MagicResistanceType
from utils.spreadsheet_bool import parse_spreadsheet_bool
from utils.spreadsheet_row import SpreadsheetRow


@dataclass(frozen=True)
class CombatCharacterDataFromSpreadsheet:
    name: str
    mastodon_id: str
    curr_hp: Optional[int]
    max_hp: int
    atk: int
    attack_range: int
    m_res: MagicResistanceType
    is_magic_attacker: bool
    max_cost: int
    passive_skill_id: str
    skill_id_list: list[str]
    # "에너미" 시트 전용 체크박스(hide_hp). "캐릭터" 시트에는 컬럼 자체가
    # 없어 기본값 False로 채워진다. 공개 노출 지점(필드 시트/전투 답글)에서
    # 체력을 "?/?"로 가리는 데 쓰인다.
    hide_hp: bool = False

    @classmethod
    def from_dict(cls, raw: SpreadsheetRow) -> "CombatCharacterDataFromSpreadsheet":
        return cls(
            name=str(raw["name"]),
            mastodon_id=str(raw["mastodon_id"]),
            curr_hp=(int(raw["curr_hp"]) if raw["curr_hp"] not in (None, "") else None),
            max_hp=int(raw["max_hp"]),
            atk=int(raw["atk"]),
            attack_range=int(raw["attack_range"]),
            m_res=MagicResistanceType(raw["m_res"]),
            is_magic_attacker=parse_spreadsheet_bool(raw["is_magic"]),
            max_cost=int(raw["max_cost"]),
            passive_skill_id=str(raw.get("passive_skill_id", "") or ""),
            skill_id_list=[
                str(raw.get(f"skill_{i + 1}_id", "") or "")
                for i in range(MAX_SKILL_SLOT_COUNT)
            ],
            hide_hp=parse_spreadsheet_bool(raw.get("hide_hp", False)),
        )
