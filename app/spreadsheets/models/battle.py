from dataclasses import dataclass

from battle.objects.define import MAX_SKILL_SLOT_COUNT, MagicResistanceType


@dataclass(frozen=True)
class CharacterDataFromSpreadsheet:
    name: str
    mastodon_id: str
    curr_hp: int
    max_hp: int
    atk: int
    attack_range: int
    m_res: MagicResistanceType
    is_magic_attacker: bool
    max_cost: int
    passive_buff_id: str
    skill_id_list: list[str]

    @classmethod
    def from_dict(
        cls, raw: dict[str, str | int | bool]
    ) -> "CharacterDataFromSpreadsheet":
        return cls(
            name=raw["name"],
            mastodon_id=raw["mastodon_id"],
            curr_hp=raw["curr_hp"],
            max_hp=raw["max_hp"],
            atk=raw["atk"],
            attack_range=raw["attack_range"],
            m_res=MagicResistanceType(raw["m_res"]),
            is_magic_attacker=raw["is_magic"],
            max_cost=raw["max_cost"],
            passive_buff_id=raw["passive_buff_id"],
            skill_id_list=[raw.get(f"skill_{i + 1}_id", "") or "" for i in range(MAX_SKILL_SLOT_COUNT)],
        )
