from typing import Optional

from battle.objects.define import (
    REVIVAL_COUNT_FOR_EXTRA_COST,
    REVIVAL_RECEIVED_DAMAGE_PERCENT_PER_COUNT,
    CombatStatType,
    MagicResistanceType,
)
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
        curr_hp: Optional[int] = None,
        revival_count: int = 0,
    ):
        self._base_atk = attack
        self._base_attack_range = attack_range
        self._curr_hp = curr_hp if curr_hp is not None else max_hp
        self._max_hp = max_hp
        self._m_res = magic_resistance
        self._is_magic_attacker = is_magic_attacker
        self._revival_count = revival_count

        # on_start_round()가 COST_PER_TURN을 그대로 채우므로, 부활 보너스는
        # 여기서 한 번만 반영해 두면 매 라운드 자동으로 유지된다.
        self._max_cost = max_cost + (
            1 if revival_count >= REVIVAL_COUNT_FOR_EXTRA_COST else 0
        )
        self._curr_cost = self._max_cost

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
        # value는 퍼센트 포인트 단위다(15 → ±15%).
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

    @property
    def revival_count(self) -> int:
        """부활 횟수 ("캐릭터" 시트에서 GM이 직접 관리하는 값)."""
        return self._revival_count

    @property
    def revival_penalty(self) -> Optional[FloatValueModifier]:
        """부활 횟수만큼 받는 대미지가 늘어나는 상시 페널티. 부활한 적이 없으면
        None을 반환한다.

        m_res와 마찬가지로 버프가 아니라 게임 메커니즘이므로 FIXED 대미지에도
        적용된다. value는 퍼센트 포인트 단위다(1회 → +10%).
        """
        if self._revival_count <= 0:
            return None
        return FloatValueModifier(
            source_name="부활 대가",
            value=self._revival_count * REVIVAL_RECEIVED_DAMAGE_PERCENT_PER_COUNT,
            applies_to_fixed=True,
        )
