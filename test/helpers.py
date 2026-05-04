from typing import Optional

from battle.objects.define import ElementType, MagicResistanceType
from spreadsheets.models.battle import CharacterDataFromSpreadsheet


def get_test_preset(
    character_name: str,
    *,
    element: ElementType = ElementType.FATE,
    atk: int = 5,
    attack_range: int = 3,
    initial_hp: Optional[int] = None,
    max_hp: int = 100,
    m_res: MagicResistanceType = MagicResistanceType.NORMAL,
    is_magic_attacker: bool = False,
    max_cost: int = 3,
    passive_buff_id: Optional[str] = None,
    skill_1_id: Optional[str] = None,
    skill_2_id: Optional[str] = None,
) -> CharacterDataFromSpreadsheet:
    return CharacterDataFromSpreadsheet(
        name=character_name,
        mastodon_id="",
        element=element,
        curr_hp=max_hp if initial_hp is None else initial_hp,
        max_hp=max_hp,
        atk=atk,
        attack_range=attack_range,
        m_res=m_res,
        is_magic_attacker=is_magic_attacker,
        max_cost=max_cost,
        passive_buff_id=passive_buff_id if passive_buff_id else "",
        skill_1_id=skill_1_id if skill_1_id else "",
        skill_2_id=skill_2_id if skill_2_id else "",
    )
