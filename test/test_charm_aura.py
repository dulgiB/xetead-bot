"""부적: 라운드 시작 때 소지자 사거리 안의 같은 진영 캐릭터(소지자 포함)에게
패시브를 1턴짜리 버프로 건다.

사거리는 "아이템" 시트의 range이고, 범위는 라운드 시작 시점의 위치로 정한다.
본 전투에서만 발동한다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.charm_aura_container import CharmBuff, charm_config_error
from battle.core.command_processors import process_ally_command
from battle.core.commands.parser import parse_character_command
from battle.objects.define import (
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
    ItemType,
    ValueSourceType,
    ValueType,
)
from battle.objects.extensions import get_total_cost
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectDamage,
    SkillEffectRevivalCountFloor,
)
from battle.objects.skill.models import SkillData
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import SideType
from bot.field_restore import _restore_buffs
from bot.log_sheets import build_field_buffs
from helpers import get_test_preset
from spreadsheets.inventory import Inventory

CHARM_ID = "부적_1"
CHARM_PASSIVE_ID = "PassiveSkill"
HOLDER = CharacterId("소지자")
NEAR = CharacterId("인접_아군")
FAR = CharacterId("먼_아군")
FOE = CharacterId("적군")

_FIXED_DAMAGE = 30


def _charm_passive(*effects) -> PassiveSkillData:
    return PassiveSkillData(
        id=CHARM_PASSIVE_ID,
        trigger=PassiveSkillTrigger.BATTLE_START,
        target_type=PassiveSkillTargetType.SELF,
        effects=list(effects)
        or [SkillEffectRevivalCountFloor(None, 4, None, None, None)],
        description="부활 4회 상태처럼 취급한다.",
    )


def _charm_item(attack_range: int = 1, passive_skill_id: str = CHARM_PASSIVE_ID):
    return ItemData(
        id=CHARM_ID,
        target_rule="",
        cost=0,
        attack_range=attack_range,
        effect=None,
        item_type=ItemType.CHARM,
        passive_skill_id=passive_skill_id,
    )


def _damage_skill() -> SkillData:
    return SkillData(
        id="Cost2Skill",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectDamage(
                ValueSourceType.FIXED, _FIXED_DAMAGE, ValueType.INTEGER, None, None
            )
        ],
        description="",
    )


def _make_context(
    owners: tuple[str, ...] = (HOLDER.name,),
    *,
    item: ItemData | None = None,
    passive: PassiveSkillData | None = None,
) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={},
        skill_dict={"Cost2Skill": _damage_skill()},
        passive_skill_dict={CHARM_PASSIVE_ID: passive or _charm_passive()},
        item_dict={CHARM_ID: item or _charm_item()},
        inventory=Inventory({(name, CHARM_ID): 1 for name in owners}),
    )


def _place(ctx, char_id, faction, column, **preset_kwargs):
    ctx.add_character(
        get_test_preset(char_id.name, **preset_kwargs),
        faction,
        BattlefieldColumnIndex(column),
    )


def _cost_per_turn(ctx, char_id) -> int:
    return ctx.characters[char_id].status[CombatStatType.COST_PER_TURN]


def _penalty(ctx, char_id) -> int:
    modifier = ctx.characters[char_id].status.revival_penalty
    return 0 if modifier is None else modifier.value


def _standard_field() -> BattlefieldContext:
    ctx = _make_context()
    _place(ctx, HOLDER, FactionType.ALLY, 3)
    _place(ctx, NEAR, FactionType.ALLY, 4)
    _place(ctx, FAR, FactionType.ALLY, 5)
    _place(ctx, FOE, FactionType.ENEMY, 3)
    ctx.on_start_round()
    return ctx


def _charm_buffs(ctx, char_id) -> list[CharmBuff]:
    return [
        buff
        for buff in ctx.buff_container.get_buffs_by(char_id, None)
        if isinstance(buff, CharmBuff)
    ]


class TestRange:
    def test_holder_and_allies_in_range_are_affected(self):
        ctx = _standard_field()

        assert _penalty(ctx, HOLDER) == 40
        assert _penalty(ctx, NEAR) == 40
        assert _cost_per_turn(ctx, HOLDER) == 4
        assert _cost_per_turn(ctx, NEAR) == 4

    def test_allies_out_of_range_are_not_affected(self):
        ctx = _standard_field()

        assert _penalty(ctx, FAR) == 0
        assert _cost_per_turn(ctx, FAR) == 3

    def test_other_faction_is_not_affected_even_in_range(self):
        ctx = _standard_field()

        assert _penalty(ctx, FOE) == 0

    def test_range_comes_from_the_item_not_the_holder(self):
        ctx = _make_context(item=_charm_item(attack_range=2))
        _place(ctx, HOLDER, FactionType.ALLY, 3, attack_range=0)
        _place(ctx, FAR, FactionType.ALLY, 5)
        ctx.on_start_round()

        assert _penalty(ctx, FAR) == 40


class TestRoundStartBuff:
    def test_nothing_applies_before_the_first_round_starts(self):
        ctx = _make_context()
        _place(ctx, HOLDER, FactionType.ALLY, 3)

        assert _penalty(ctx, HOLDER) == 0

    def test_effect_is_a_one_turn_buff(self):
        ctx = _standard_field()

        (buff,) = _charm_buffs(ctx, NEAR)
        assert buff.given_by == HOLDER
        assert buff.duration.remaining_turns == 1
        assert buff.display_id_label() == f"{CHARM_ID}[{HOLDER.name}]"
        assert _charm_buffs(ctx, FAR) == []

    def test_round_end_removes_the_buff_and_its_effect(self):
        ctx = _standard_field()

        ctx.on_finish_round()

        assert _charm_buffs(ctx, NEAR) == []
        assert _penalty(ctx, NEAR) == 0
        assert _cost_per_turn(ctx, NEAR) == 3

    def test_next_round_start_grants_again_without_stacking(self):
        ctx = _standard_field()

        ctx.on_finish_round()
        ctx.on_start_round()

        assert len(_charm_buffs(ctx, NEAR)) == 1
        assert _penalty(ctx, NEAR) == 40

    def test_regrant_while_still_active_does_not_double_count(self):
        """복원 직후 등 버프가 남아 있는 채로 라운드가 시작돼도 하한이
        두 번 얹히지 않는다 — 되돌릴 때 하나가 남으면 영구히 붙는다."""
        ctx = _standard_field()

        ctx.on_start_round()
        ctx.on_finish_round()

        assert _penalty(ctx, NEAR) == 0


class TestRangeFixedAtRoundStart:
    def test_moving_into_range_mid_round_does_not_apply(self):
        """코스트 보너스 없이 받는 대미지 증가만 떠안는 경우를 막는다."""
        ctx = _standard_field()

        ctx.move_character_to(FAR, BattlefieldColumnIndex(2))

        assert _penalty(ctx, FAR) == 0

    def test_moving_out_of_range_mid_round_keeps_the_buff(self):
        """코스트 보너스를 이미 받았으니 대가도 그 라운드 동안 유지된다."""
        ctx = _standard_field()

        ctx.move_character_to(NEAR, BattlefieldColumnIndex(6))

        assert _penalty(ctx, NEAR) == 40
        assert ctx.characters[NEAR].status.remaining_cost == 4

    def test_new_position_counts_from_the_next_round(self):
        ctx = _standard_field()
        ctx.move_character_to(NEAR, BattlefieldColumnIndex(6))
        ctx.move_character_to(FAR, BattlefieldColumnIndex(2))

        ctx.on_finish_round()
        ctx.on_start_round()

        assert _penalty(ctx, NEAR) == 0
        assert ctx.characters[NEAR].status.remaining_cost == 3
        assert _penalty(ctx, FAR) == 40
        assert ctx.characters[FAR].status.remaining_cost == 4

    def test_holder_moving_changes_the_range_from_the_next_round(self):
        ctx = _standard_field()

        ctx.move_character_to(HOLDER, BattlefieldColumnIndex(6))
        assert _penalty(ctx, NEAR) == 40
        assert _penalty(ctx, FAR) == 0

        ctx.on_finish_round()
        ctx.on_start_round()
        assert _penalty(ctx, NEAR) == 0
        assert _penalty(ctx, FAR) == 40
        assert _penalty(ctx, HOLDER) == 40

    def test_holder_leaving_keeps_this_rounds_buffs(self):
        ctx = _standard_field()

        ctx.remove_character(HOLDER)
        assert _penalty(ctx, NEAR) == 40

        ctx.on_finish_round()
        ctx.on_start_round()
        assert _penalty(ctx, NEAR) == 0

    def test_two_holders_overlap_without_double_counting(self):
        ctx = _make_context(owners=(HOLDER.name, NEAR.name))
        _place(ctx, HOLDER, FactionType.ALLY, 3)
        _place(ctx, NEAR, FactionType.ALLY, 4)
        ctx.on_start_round()

        assert len(_charm_buffs(ctx, HOLDER)) == 2
        assert _penalty(ctx, HOLDER) == 40
        ctx.on_finish_round()
        assert _penalty(ctx, HOLDER) == 0


class TestRestore:
    def test_snapshot_round_trip_keeps_the_round_start_range(self):
        """복원은 위치로 다시 계산하지 않는다 — 라운드 도중 범위 밖으로
        나간 캐릭터도 그 라운드의 버프를 이어받는다."""
        ctx = _standard_field()
        ctx.move_character_to(NEAR, BattlefieldColumnIndex(6))
        snapshot = [
            {"name": char_id.name, "buffs": build_field_buffs(ctx, char_id)}
            for char_id in (HOLDER, NEAR, FAR)
        ]

        restored = _make_context()
        _place(restored, HOLDER, FactionType.ALLY, 3)
        _place(restored, NEAR, FactionType.ALLY, 6)
        _place(restored, FAR, FactionType.ALLY, 5)
        restored.on_battle_start()

        assert _restore_buffs(restored, snapshot) == 2
        assert _penalty(restored, NEAR) == 40
        assert _penalty(restored, FAR) == 0
        restored.on_finish_round()
        assert _penalty(restored, NEAR) == 0

    def test_unknown_charm_is_skipped(self):
        ctx = _make_context()
        _place(ctx, NEAR, FactionType.ALLY, 3)
        snapshot = [
            {"name": NEAR.name, "buffs": [{"charm": CHARM_ID, "given_by": "불참자"}]}
        ]

        assert _restore_buffs(ctx, snapshot) == 0
        assert _penalty(ctx, NEAR) == 0


class TestRevivalFloor:
    def test_counts_as_four_revivals_for_received_damage(self):
        """받는 대미지가 (4 - 부활 횟수) × 10%만큼 더 늘어 총 40%가 된다."""
        ctx = _make_context()
        _place(ctx, HOLDER, FactionType.ALLY, 3, revival_count=2)
        ctx.on_start_round()

        assert _penalty(ctx, HOLDER) == 40

    def test_more_revivals_than_the_floor_keep_their_own_count(self):
        ctx = _make_context()
        _place(ctx, HOLDER, FactionType.ALLY, 3, revival_count=5)
        ctx.on_start_round()

        assert _penalty(ctx, HOLDER) == 50
        # 이미 4회 이상이라 받던 +1에 더 얹지 않는다.
        assert _cost_per_turn(ctx, HOLDER) == 4

    def test_damage_end_to_end(self):
        """진영과 무관하게 같은 진영에 건다 — 적군 소지자로 대미지를 확인한다."""
        ctx = _make_context(owners=(FOE.name,))
        _place(ctx, NEAR, FactionType.ALLY, 3, skill_1_id="Cost2Skill")
        _place(ctx, FOE, FactionType.ENEMY, 3)
        ctx.on_start_round()

        command = parse_character_command(NEAR, f"[Cost2Skill/{FOE.name}]", ctx)
        assert command is not None
        process_ally_command(ctx, command)

        assert 100 - ctx.characters[FOE].status.curr_hp == 42  # 30 × 1.4

    def test_cost_per_turn_is_refilled_at_round_start(self):
        ctx = _standard_field()
        ctx.characters[NEAR].status.remaining_cost = 0

        ctx.on_start_round()

        assert ctx.characters[NEAR].status.remaining_cost == 4

    def test_move_cost_uses_the_real_revival_count(self):
        ctx = _standard_field()

        command = parse_character_command(NEAR, "[이동/4]", ctx)
        assert command is not None
        assert get_total_cost(command.parts, NEAR, ctx) == 1

    def test_real_revival_count_is_unchanged(self):
        """키워드 보정 자격 등은 실제 부활 횟수를 본다."""
        ctx = _standard_field()

        assert ctx.characters[NEAR].status.revival_count == 0


class TestOwnership:
    def test_owner_not_in_battle_has_no_effect(self):
        ctx = _make_context(owners=("불참자",))
        _place(ctx, NEAR, FactionType.ALLY, 3)
        ctx.on_start_round()

        assert _penalty(ctx, NEAR) == 0

    def test_zero_count_does_not_count_as_owned(self):
        ctx = _make_context()
        ctx.inventory = Inventory({(HOLDER.name, CHARM_ID): 0})
        _place(ctx, HOLDER, FactionType.ALLY, 3)
        ctx.on_start_round()

        assert _penalty(ctx, HOLDER) == 0

    def test_non_charm_item_is_ignored(self):
        item = ItemData(
            id=CHARM_ID,
            target_rule="",
            cost=0,
            attack_range=1,
            effect=None,
            item_type=ItemType.ETC,
            passive_skill_id=CHARM_PASSIVE_ID,
        )
        ctx = _make_context(item=item)
        _place(ctx, HOLDER, FactionType.ALLY, 3)
        ctx.on_start_round()

        assert _penalty(ctx, HOLDER) == 0

    def test_missing_passive_does_not_break_placement(self):
        ctx = _make_context(item=_charm_item(passive_skill_id="사라진패시브"))
        _place(ctx, HOLDER, FactionType.ALLY, 3)
        ctx.on_start_round()

        assert _penalty(ctx, HOLDER) == 0


class TestPracticeModesExcluded:
    def test_charm_does_not_apply_in_practice(self):
        ctx = PracticeBattlefieldContext(
            buff_dict={},
            skill_dict={},
            passive_skill_dict={CHARM_PASSIVE_ID: _charm_passive()},
            item_dict={CHARM_ID: _charm_item()},
        )
        # 막는 것이 "인벤토리가 비어 있어서"가 아니라 allow_charms임을
        # 드러내려고 직접 채운다.
        ctx.inventory = Inventory({("대련_1", CHARM_ID): 1})
        ctx.add_character(
            get_test_preset("대련_1"), SideType.SIDE_1, BattlefieldColumnIndex(0)
        )
        ctx.on_start_round()

        status = ctx.characters[CharacterId("대련_1")].status
        assert status.revival_penalty is None


class TestConfigError:
    def test_valid_charm_has_no_error(self):
        assert charm_config_error(_charm_item(), _charm_passive()) is None

    def test_missing_passive_is_reported(self):
        error = charm_config_error(_charm_item(), None)
        assert error is not None and CHARM_PASSIVE_ID in error

    def test_triggered_effect_is_reported(self):
        passive = _charm_passive(SkillEffectAddBuff(None, None, None, "SomeBuff", None))
        error = charm_config_error(_charm_item(), passive)
        assert error is not None and "SkillEffectAddBuff" in error
