"""합동 스킬: 짝이 같은 라운드에 함께 선언해야 한 번 발동하는 스킬.

먼저 선언한 쪽은 코스트만 내고 대기하고, 짝이 선언하면 먼저 선언한 쪽을
시전자로 효과가 나간다. 라운드가 끝날 때까지 짝이 오지 않으면 대기만 풀리고
코스트는 돌려주지 않는다. 스킬마다 전투당 한 번만 쓸 수 있다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import BattleLogEntryKind
from battle.core.commands.parser import parse_character_command
from battle.core.joint_skill import dump_joint_state, load_joint_state
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.define import SkillValueType
from battle.objects.skill.effects import SkillEffectDamage
from battle.objects.skill.models import SkillData
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import SideType
from helpers import get_test_preset

JOINT_SKILL_ID = "합동_1"
FIRST = "아군_1"
SECOND = "아군_2"
ENEMY = "적군"


def _joint_skill(
    *, unlocked: bool = True, paired: tuple[str, ...] = (FIRST, SECOND)
) -> SkillData:
    return SkillData(
        id=JOINT_SKILL_ID,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=3,
        effects=[
            SkillEffectDamage(
                value_source=ValueSourceType.JOINT_ATK_ROLL_SUM,
                value=100,
                value_type=SkillValueType.PERCENT,
                buff_id=None,
                buff_add_timing=None,
            )
        ],
        description="",
        paired_characters=paired,
        joint_unlocked=unlocked,
    )


def _make_context(
    *,
    unlocked: bool = True,
    second_name: str = SECOND,
    second_range: int = 3,
    place_second: bool = True,
) -> BattlefieldContext:
    ctx = BattlefieldContext(
        buff_dict={},
        skill_dict={JOINT_SKILL_ID: _joint_skill(unlocked=unlocked)},
    )
    ctx.add_character(
        get_test_preset(FIRST, atk=5), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    if place_second:
        ctx.add_character(
            get_test_preset(second_name, atk=7, attack_range=second_range),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )
    ctx.add_character(
        get_test_preset(ENEMY, max_hp=1000),
        FactionType.ENEMY,
        BattlefieldColumnIndex(2),
    )
    return ctx


def _start(ctx: BattlefieldContext) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    return manager


def _declare(manager: RoundManager, ctx: BattlefieldContext, user: str, text: str):
    manager.process_command(parse_character_command(CharacterId(user), text, ctx))


def _hp(ctx: BattlefieldContext, name: str) -> int:
    return ctx.characters[CharacterId(name)].status.curr_hp


@pytest.fixture(autouse=True)
def _fixed_dice(monkeypatch):
    monkeypatch.setattr("utils.dice.random.randint", lambda a, b: 1)


class TestDeclaration:
    def test_first_declaration_only_pays_and_waits(self):
        ctx = _make_context()
        manager = _start(ctx)

        _declare(manager, ctx, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")

        assert _hp(ctx, ENEMY) == 1000
        assert ctx.characters[CharacterId(FIRST)].status.remaining_cost == 0
        assert JOINT_SKILL_ID in ctx.joint_pending
        assert [
            entry.kind for result in ctx.results for entry in result.log_entries
        ] == [BattleLogEntryKind.JOINT_SKILL]

    def test_partner_fires_it_once_with_both_rolls(self):
        """공격력 5 + 7과 두 사람의 1d6(고정 1)을 더한 값의 100%."""
        ctx = _make_context()
        manager = _start(ctx)

        _declare(manager, ctx, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")
        _declare(manager, ctx, SECOND, f"[{JOINT_SKILL_ID}]")

        assert _hp(ctx, ENEMY) == 1000 - (5 + 7 + 1 + 1)
        assert ctx.characters[CharacterId(SECOND)].status.remaining_cost == 0
        assert JOINT_SKILL_ID not in ctx.joint_pending
        assert JOINT_SKILL_ID in ctx.joint_used

    def test_first_declarer_is_the_caster(self):
        ctx = _make_context()
        manager = _start(ctx)

        _declare(manager, ctx, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")
        _declare(manager, ctx, SECOND, f"[{JOINT_SKILL_ID}/{ENEMY}]")

        damage = [
            data
            for result in ctx.results
            for effect in result.expanded_part.data_per_effect
            if effect is not None
            for data in effect.damage_list
        ]
        assert [d.attacker_id for d in damage] == [CharacterId(FIRST)]

    def test_test_row_suffix_is_ignored_when_matching_partners(self):
        ctx = _make_context(second_name=f"{SECOND}(테스트)")
        manager = _start(ctx)

        _declare(manager, ctx, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")
        _declare(manager, ctx, f"{SECOND}(테스트)", f"[{JOINT_SKILL_ID}]")

        assert JOINT_SKILL_ID in ctx.joint_used


class TestRejections:
    def _expect_rejected(self, ctx, manager, user, text):
        with pytest.raises(CommandValidationError):
            _declare(manager, ctx, user, text)

    def test_locked_skill(self):
        ctx = _make_context(unlocked=False)
        self._expect_rejected(ctx, _start(ctx), FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")

    def test_partner_not_on_field(self):
        ctx = _make_context(place_second=False)
        self._expect_rejected(ctx, _start(ctx), FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")

    def test_target_out_of_partner_range(self):
        ctx = _make_context(second_range=0)
        self._expect_rejected(ctx, _start(ctx), FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")

    def test_keyword_boost(self):
        ctx = _make_context()
        self._expect_rejected(ctx, _start(ctx), FIRST, f"[{JOINT_SKILL_ID}+/{ENEMY}]")

    def test_declaring_twice_while_waiting(self):
        ctx = _make_context()
        manager = _start(ctx)
        _declare(manager, ctx, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")
        ctx.characters[CharacterId(FIRST)].status.remaining_cost = 3

        self._expect_rejected(ctx, manager, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")

    def test_partner_naming_a_different_target(self):
        ctx = _make_context()
        manager = _start(ctx)
        _declare(manager, ctx, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")

        self._expect_rejected(ctx, manager, SECOND, f"[{JOINT_SKILL_ID}/{FIRST}]")
        assert ctx.characters[CharacterId(SECOND)].status.remaining_cost == 3

    def test_once_per_battle_per_skill(self):
        ctx = _make_context()
        manager = _start(ctx)
        _declare(manager, ctx, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")
        _declare(manager, ctx, SECOND, f"[{JOINT_SKILL_ID}]")
        ctx.on_finish_round()
        ctx.on_start_round()

        self._expect_rejected(ctx, manager, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")


class TestRoundEnd:
    def test_unanswered_declaration_expires_without_refund(self):
        ctx = _make_context()
        manager = _start(ctx)
        _declare(manager, ctx, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")

        entries, _ = ctx.on_finish_round()

        assert ctx.joint_pending == {}
        assert JOINT_SKILL_ID not in ctx.joint_used
        assert ctx.characters[CharacterId(FIRST)].status.remaining_cost == 0
        assert [e.kind for e in entries] == [BattleLogEntryKind.JOINT_SKILL]
        assert [e.target_name for e in entries] == [FIRST]


class TestAvailability:
    def test_not_granted_in_practice_battles(self):
        ctx = PracticeBattlefieldContext(
            buff_dict={},
            skill_dict={JOINT_SKILL_ID: _joint_skill()},
        )
        ctx.add_character(
            get_test_preset(FIRST), SideType.SIDE_1, BattlefieldColumnIndex(0)
        )

        skills = ctx.characters[CharacterId(FIRST)].skills
        assert [s.data.id for s in skills] == []

    def test_only_partners_get_it(self):
        ctx = _make_context()
        ctx.add_character(
            get_test_preset("아군_3"), FactionType.ALLY, BattlefieldColumnIndex(3)
        )

        assert [s.data.id for s in ctx.characters[CharacterId(FIRST)].skills] == [
            JOINT_SKILL_ID
        ]
        assert ctx.characters[CharacterId("아군_3")].skills == []


class TestPersistence:
    def test_state_survives_a_restart(self):
        ctx = _make_context()
        manager = _start(ctx)
        _declare(manager, ctx, FIRST, f"[{JOINT_SKILL_ID}/{ENEMY}]")
        ctx.joint_used.add("합동_2")

        restored = _make_context()
        load_joint_state(restored, dump_joint_state(ctx))

        assert restored.joint_used == {"합동_2"}
        assert restored.joint_pending == ctx.joint_pending


class TestSheetParsing:
    def _row(self, **extra) -> dict:
        return {
            "id": JOINT_SKILL_ID,
            "target_rule": "SkillTargetRuleNamed",
            "target_count": 1,
            "cost": 3,
            "description": "",
            **extra,
        }

    def test_paired_columns_make_it_joint(self):
        data = SkillData.from_dict(
            self._row(
                paired_character_0=FIRST,
                paired_character_1=SECOND,
                is_joint_unlocked=True,
            )
        )

        assert data.is_joint
        assert data.paired_characters == (FIRST, SECOND)
        assert data.joint_unlocked

    def test_regular_skill_is_untouched(self):
        data = SkillData.from_dict(self._row())

        assert not data.is_joint
        assert not data.joint_unlocked
