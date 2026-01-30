from battle.core.battlefield_context import BattlefieldColumnIndex


def is_reachable(
    ref_pos: BattlefieldColumnIndex,
    target_pos: BattlefieldColumnIndex,
    reachable_range: int,
) -> bool:
    return target_pos.value in range(
        max(0, ref_pos.value - reachable_range),
        min(7, ref_pos.value + reachable_range + 1),
    )
