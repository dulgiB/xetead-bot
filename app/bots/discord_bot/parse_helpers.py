from typing import Optional

from battle.objects.define import MagicResistanceType


def parse_attack_type(s: str) -> bool:
    if s == "물리":
        return False
    if s == "마법":
        return True
    raise ValueError(f"공격 속성은 '물리' 또는 '마법'이어야 합니다. (입력: {s!r})")


def parse_m_res(s: str) -> MagicResistanceType:
    mapping = {
        "낮음": MagicResistanceType.WEAK,
        "보통": MagicResistanceType.NORMAL,
        "높음": MagicResistanceType.STRONG,
    }
    if s not in mapping:
        raise ValueError(
            f"마법 저항은 '낮음', '보통', '높음' 중 하나여야 합니다. (입력: {s!r})"
        )
    return mapping[s]


def validate_stats(atk: int, hp: int, rng: int) -> Optional[str]:
    if not (3 <= atk <= 12):
        return f"공격력은 3~12 범위여야 합니다. (입력값: {atk})"
    if not (60 <= hp <= 100):
        return f"체력은 60~100 범위여야 합니다. (입력값: {hp})"
    if not (1 <= rng <= 3):
        return f"사거리는 1~3 범위여야 합니다. (입력값: {rng})"
    return None
