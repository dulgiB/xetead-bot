from dataclasses import dataclass

from battle.objects.define import CombatStatType, MagicResistanceType
from battle.objects.models import FloatValueModifier


@dataclass
class CombatStats:
    def __init__(
        self,
        attack: int,
        max_hp: int,
        attack_range: int,
        magic_resistance: MagicResistanceType,
        max_cost: int,
        curr_hp: int = None,
    ):
        self._base_atk = attack
        self._base_attack_range = attack_range
        self._curr_hp = curr_hp if curr_hp is not None else max_hp
        self._max_hp = max_hp
        self._m_res = magic_resistance

        self._curr_cost = max_cost
        self._max_cost = max_cost

    def __getitem__(self, item: CombatStatType):
        if item == CombatStatType.ATK:
            return self._base_atk
        elif item == CombatStatType.RANGE:
            return self._base_attack_range
        elif item == CombatStatType.COST_PER_TURN:
            return self._max_cost
        elif item == CombatStatType.MAX_HP:
            return self._max_hp
        else:
            raise ValueError(f"Unknown CombatStatType: {item}")

    @property
    def curr_hp(self):
        return self._curr_hp

    @curr_hp.setter
    def curr_hp(self, new_hp: int):
        self._curr_hp = new_hp

    @property
    def remaining_cost(self):
        return self._curr_cost

    @remaining_cost.setter
    def remaining_cost(self, new_cost: int):
        self._curr_cost = new_cost

    @property
    def m_res(self) -> FloatValueModifier:
        if self._m_res == MagicResistanceType.WEAK:
            return FloatValueModifier(0.1)
        elif self._m_res == MagicResistanceType.NORMAL:
            return FloatValueModifier(0)
        elif self._m_res == MagicResistanceType.STRONG:
            return FloatValueModifier(-0.1)
        else:
            raise ValueError(f"Unknown MagicResistanceType: {self._m_res}")
