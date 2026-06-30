from typing import Optional

from battle.objects.define import MagicResistanceType
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet


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
    )
