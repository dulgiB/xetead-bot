from collections.abc import Iterable

from battle.objects.define import BattlefieldColumnIndex

# NONE(7)이 "열 없음" 센티넬이라 유효한 열 index는 0..6이다.
COLUMN_COUNT = BattlefieldColumnIndex.NONE.value


def columns_for_span(
    anchor: BattlefieldColumnIndex, span: int
) -> tuple[BattlefieldColumnIndex, ...]:
    """가장 왼쪽 열(anchor)과 차지하는 열 수(span)로 점유 열 목록을 만든다.
    전장 밖으로 넘어가는 열은 잘라낸다."""
    if anchor == BattlefieldColumnIndex.NONE:
        return (anchor,)
    last = min(COLUMN_COUNT - 1, anchor.value + max(1, span) - 1)
    return tuple(
        BattlefieldColumnIndex(value) for value in range(anchor.value, last + 1)
    )


def is_reachable(
    ref_pos: BattlefieldColumnIndex,
    target_pos: BattlefieldColumnIndex,
    reachable_range: int,
) -> bool:
    return target_pos.value in range(
        max(0, ref_pos.value - reachable_range),
        min(COLUMN_COUNT, ref_pos.value + reachable_range + 1),
    )


def is_reachable_between(
    ref_columns: Iterable[BattlefieldColumnIndex],
    target_columns: Iterable[BattlefieldColumnIndex],
    reachable_range: int,
) -> bool:
    """여러 열을 차지하는 쪽이 섞여 있을 때의 사거리 판정.

    한쪽의 어느 열에서든 다른 쪽의 어느 열에 닿으면 도달한 것으로 본다.
    "점유 열 중 하나라도 사거리 안이면 공격 가능"과 "다열 에너미는 양 끝
    열을 기준으로 범위를 책정"은 이 규칙의 양면이다.
    """
    target_list = list(target_columns)
    return any(
        is_reachable(ref, target, reachable_range)
        for ref in ref_columns
        for target in target_list
    )


def columns_overlap(
    columns_a: Iterable[BattlefieldColumnIndex],
    columns_b: Iterable[BattlefieldColumnIndex],
) -> bool:
    """두 점유 열 목록이 한 열이라도 겹치는지. "같은 열" 판정의 다열 확장이다."""
    return bool(set(columns_a) & set(columns_b))
