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

        # 필드 효과가 얹는 스탯 증감. 버프가 아니라 전장 상태이므로
        # BuffedStats(계산기 안에서만 사는 객체)가 아니라 여기에 둔다 —
        # 사거리는 사거리 검증·범위 조건·필드 시트 표시가 모두 이 값을
        # 직접 읽으므로, 여기 얹지 않으면 아무 데도 반영되지 않는다.
        self._stat_offsets: dict[CombatStatType, int] = {}

    def __getitem__(self, item: CombatStatType) -> int:
        return self._base_stat(item) + self._stat_offsets.get(item, 0)

    def _base_stat(self, item: CombatStatType) -> int:
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

    def add_stat_offset(self, stat_type: CombatStatType, delta: int) -> None:
        """스탯 증감을 얹는다. 같은 스탯에 여러 필드 효과가 걸리면 합산된다.

        결과가 음수가 되지 않도록 __getitem__에서 자르지는 않는다 — 자르면
        remove_stat_offset()이 원래 값으로 되돌리지 못한다. 음수가 곤란한
        지점(사거리 등)은 읽는 쪽이 판단한다.
        """
        self._stat_offsets[stat_type] = self._stat_offsets.get(stat_type, 0) + delta

    def remove_stat_offset(self, stat_type: CombatStatType, delta: int) -> None:
        """add_stat_offset()으로 얹은 증감을 정확히 같은 양만큼 되돌린다."""
        self.add_stat_offset(stat_type, -delta)

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
            source_name="부활",
            value=self._revival_count * REVIVAL_RECEIVED_DAMAGE_PERCENT_PER_COUNT,
            applies_to_fixed=True,
        )
