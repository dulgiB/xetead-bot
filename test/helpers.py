from collections.abc import Mapping
from typing import Any, Optional

from gspread.utils import a1_to_rowcol

from battle.objects.define import MagicResistanceType
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet


def apply_values_batch_update(
    sheets_by_title: Mapping[str, Any], body: Mapping[str, Any]
) -> None:
    """가짜 스프레드시트에서 `values.batchUpdate`를 흉내낸다.

    log_sheets가 체력을 캐릭터별 update_cell이 아니라 배치 한 번으로 쓰므로,
    가짜 스프레드시트도 그 호출을 받아야 한다. 범위를 풀어 해당 가짜
    워크시트의 update_cell()로 분배해, 테스트가 기존처럼 워크시트 단위로
    쓰기를 확인할 수 있게 한다.
    """
    for item in body["data"]:
        title, _, cell = str(item["range"]).rpartition("!")
        title = title.strip("'").replace("''", "'")
        row, col = a1_to_rowcol(cell)
        sheets_by_title[title].update_cell(row, col, item["values"][0][0])


def get_test_preset(
    character_name: str,
    *,
    atk: int = 5,
    attack_range: int = 3,
    initial_hp: Optional[int] = None,
    max_hp: int = 100,
    m_res: MagicResistanceType = MagicResistanceType.NORMAL,
    is_magic_attacker: bool = False,
    max_cost: int = 3,
    passive_skill_id: Optional[str] = None,
    skill_1_id: Optional[str] = None,
    skill_2_id: Optional[str] = None,
    skill_3_id: Optional[str] = None,
    revival_count: int = 0,
    fate_date: str = "",
    hide_hp: bool = False,
    span: int = 1,
) -> CombatCharacterDataFromSpreadsheet:
    return CombatCharacterDataFromSpreadsheet(
        name=character_name,
        mastodon_id="",
        curr_hp=max_hp if initial_hp is None else initial_hp,
        max_hp=max_hp,
        atk=atk,
        attack_range=attack_range,
        m_res=m_res,
        is_magic_attacker=is_magic_attacker,
        max_cost=max_cost,
        passive_skill_id=passive_skill_id if passive_skill_id else "",
        skill_id_list=[
            skill_1_id if skill_1_id else "",
            skill_2_id if skill_2_id else "",
            skill_3_id if skill_3_id else "",
        ],
        hide_hp=hide_hp,
        span=span,
        revival_count=revival_count,
        fate_date=fate_date,
    )
