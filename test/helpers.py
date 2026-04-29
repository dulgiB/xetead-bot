from typing import Optional

from battle.objects.define import ElementType, MagicResistanceType
from spreadsheets.models.battle import CharacterDataFromSpreadsheet


def get_test_preset(
    character_name: str,
    *,
    initial_hp: Optional[int] = None,
    passive_buff_id: Optional[str] = None,
    skill_1_id: Optional[str] = None,
    skill_2_id: Optional[str] = None,
) -> CharacterDataFromSpreadsheet:
    return CharacterDataFromSpreadsheet(
        name=character_name,
        mastodon_id="",
        element=ElementType.FATE,
        curr_hp=initial_hp if initial_hp else 100,
        max_hp=100,
        atk=5,
        attack_range=3,
        m_res=MagicResistanceType.NORMAL,
        is_magic_attacker=False,
        max_cost=3,
        passive_buff_id=passive_buff_id if passive_buff_id else "",
        skill_1_id=skill_1_id if skill_1_id else "",
        skill_2_id=skill_2_id if skill_2_id else "",
    )
