from battle.objects.models import CharacterId, ValueWithModifiers


def print_apply_damage(
    attacker_id: CharacterId,
    target_id: CharacterId,
    damage_value: ValueWithModifiers,
    final_value: int,
) -> None:
    print(
        f"[apply_damage] {attacker_id} > {target_id} | {damage_value} → -{final_value}"
    )


def print_apply_heal(
    healer_id: CharacterId,
    target_id: CharacterId,
    heal_value: ValueWithModifiers,
    final_value: int,
) -> None:
    print(f"[apply_heal] {healer_id} > {target_id} | {heal_value} → +{final_value}")
