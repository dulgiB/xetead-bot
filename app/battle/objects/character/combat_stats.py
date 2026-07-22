from battle.objects.define import CombatStatType, MagicResistanceType
from battle.objects.models import FloatValueModifier


class CombatStats:
    def __init__(
        self,
        attack: int,
        max_hp: int,
        attack_range: int,
        magic_resistance: MagicResistanceType,
        is_magic_attacker: bool,
        max_cost: int,
        curr_hp: int = None,
    ):
        self._base_atk = attack
        self._base_attack_range = attack_range
        self._curr_hp = curr_hp if curr_hp is not None else max_hp
        self._max_hp = max_hp
        self._m_res = magic_resistance
        self._is_magic_attacker = is_magic_attacker

        self._curr_cost = max_cost
        self._max_cost = max_cost

    def __getitem__(self, item: CombatStatType) -> int:
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
        # 버프가 아니라 게임 메커니즘이므로 FIXED 대미지에도 적용된다.
        # value는 다른 FloatValueModifier와 동일하게 퍼센트 포인트 단위다
        # (15 → ±15%, ValueWithModifiers가 value/100으로 나눠 배율을 만든다).
        if self._m_res == MagicResistanceType.WEAK:
            return FloatValueModifier(
                source_name="마법 저항", value=15, applies_to_fixed=True
            )
        elif self._m_res == MagicResistanceType.NORMAL:
            return FloatValueModifier(
                source_name="마법 저항", value=0, applies_to_fixed=True
            )
        elif self._m_res == MagicResistanceType.STRONG:
            return FloatValueModifier(
                source_name="마법 저항", value=-15, applies_to_fixed=True
            )
        else:
            raise ValueError(f"Unknown MagicResistanceType: {self._m_res}")

    @property
    def is_magic_attacker(self) -> bool:
        return self._is_magic_attacker
