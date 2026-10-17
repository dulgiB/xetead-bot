"""소환 스킬: 열 1개와 필드에 없는 에너미 1명을 지정해 그 열에 바로 배치한다.

소환할 캐릭터는 "에너미" 시트 명단(summon_roster_source)에서 찾고, 처리
시점은 이동과 같다 — 에너미 스킬이면 행동 선언(PRE) 때 바로 필드에 나타나고,
코스트가 가득 찬 채 들어와 같은 라운드에 행동할 수 있다.
"""

import pytest

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import BattleLogEntryKind
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    ActionType,
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectSummon
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

SUMMON_SKILL_ID = "스킬_1"
STRIKE_SKILL_ID = "스킬_2"

SUMMONER = CharacterId("시전자")
SUMMONED = CharacterId("에너미_1")
ALLY = CharacterId("아군_1")


def _summon_skill() -> SkillData:
    return SkillData(
        id=SUMMON_SKILL_ID,
        target_rule="SkillTargetRuleSummon",
        target_count=2,
        cost=1,
        effects=[SkillEffectSummon(None, None, None, None, None)],
        description="",
    )


def _strike_skill() -> SkillData:
    return SkillData(
        id=STRIKE_SKILL_ID,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None)
        ],
        description="",
    )


def _roster(**overrides) -> dict:
    roster = {
        "에너미_1": get_test_preset(
            "에너미_1", max_cost=4, skill_1_id=STRIKE_SKILL_ID, is_enemy=True
        ),
        "에너미_2": get_test_preset("에너미_2", initial_hp=0, is_enemy=True),
        "에너미_3": get_test_preset("에너미_3", span=2, is_enemy=True),
        # "캐릭터" 시트의 행. 소환 대상이 아니다.
        "동료_1": get_test_preset("동료_1"),
    }
    roster.update(overrides)
    return roster


def _setup() -> tuple[BattlefieldContext, RoundManager]:
    ctx = BattlefieldContext(
        buff_dict={},
        skill_dict={
            SUMMON_SKILL_ID: _summon_skill(),
            STRIKE_SKILL_ID: _strike_skill(),
        },
    )
    roster = _roster()
    ctx.summon_roster_source = lambda: roster
    ctx.add_character(
        get_test_preset(SUMMONER.name, skill_1_id=SUMMON_SKILL_ID),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset(ALLY.name), FactionType.ALLY, BattlefieldColumnIndex(2)
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return ctx, manager


def _declare(
    ctx: BattlefieldContext, manager: RoundManager, text: str, user=SUMMONER
) -> None:
    manager.process_command(parse_character_command(user, text, ctx))


class TestSummon:
    def test_summoned_enemy_appears_in_the_column_on_declaration(self):
        ctx, manager = _setup()

        _declare(ctx, manager, f"[{SUMMON_SKILL_ID}/3열/에너미_1]")

        assert SUMMONED in ctx.characters
        assert ctx.characters[SUMMONED].faction == FactionType.ENEMY
        assert ctx.find_character_position(SUMMONED) == BattlefieldColumnIndex(2)

    def test_targets_can_be_written_in_either_order(self):
        ctx, manager = _setup()

        _declare(ctx, manager, f"[{SUMMON_SKILL_ID}/에너미_1/3열]")

        assert ctx.find_character_position(SUMMONED) == BattlefieldColumnIndex(2)

    def test_name_ignores_whitespace_differences(self):
        ctx, manager = _setup()

        _declare(ctx, manager, f"[{SUMMON_SKILL_ID}/3열/에너미 _1]")

        assert SUMMONED in ctx.characters

    def test_summoned_enemy_has_full_cost_and_can_act_this_round(self):
        ctx, manager = _setup()

        _declare(ctx, manager, f"[{SUMMON_SKILL_ID}/3열/에너미_1]")

        status = ctx.characters[SUMMONED].status
        assert status.remaining_cost == status[CombatStatType.COST_PER_TURN] == 4
        assert status.round_max_cost == 4

        _declare(ctx, manager, f"[{STRIKE_SKILL_ID}/{ALLY.name}]", user=SUMMONED)
        assert status.remaining_cost == 2

    def test_summoner_pays_skill_cost(self):
        ctx, manager = _setup()

        _declare(ctx, manager, f"[{SUMMON_SKILL_ID}/3열/에너미_1]")

        assert ctx.characters[SUMMONER].status.remaining_cost == 2

    def test_summon_is_reported_as_a_log_entry(self):
        ctx, manager = _setup()

        _declare(ctx, manager, f"[{SUMMON_SKILL_ID}/3열/에너미_1]")

        entries = [
            entry
            for result in ctx.results
            for entry in result.log_entries
            if entry.kind == BattleLogEntryKind.SUMMON
        ]
        assert [(e.target_name, e.result) for e in entries] == [
            ("에너미_1", "3열에 소환")
        ]

    def test_post_action_does_not_summon_again(self):
        ctx, manager = _setup()
        _declare(ctx, manager, f"[{SUMMON_SKILL_ID}/3열/에너미_1]")
        manager.to_phase(RoundPhaseType.ALLY_ACTION)

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        post_entries = [
            entry
            for result in manager.get_last_post_action_results()[SUMMONER]
            for entry in result.log_entries
        ]
        assert post_entries == []
        assert list(ctx.characters).count(SUMMONED) == 1

    def test_multi_column_enemy_occupies_every_column(self):
        ctx, manager = _setup()

        _declare(ctx, manager, f"[{SUMMON_SKILL_ID}/3열/에너미_3]")

        assert tuple(ctx.find_character_columns(CharacterId("에너미_3"))) == (
            BattlefieldColumnIndex(2),
            BattlefieldColumnIndex(3),
        )


class TestRejected:
    @pytest.mark.parametrize(
        "text",
        [
            # 이미 필드에 있다
            f"[{SUMMON_SKILL_ID}/3열/{SUMMONER.name}]",
            # 명단에 없다
            f"[{SUMMON_SKILL_ID}/3열/없는_이름]",
            # "캐릭터" 시트의 행이다
            f"[{SUMMON_SKILL_ID}/3열/동료_1]",
            # 체력 0
            f"[{SUMMON_SKILL_ID}/3열/에너미_2]",
            # 2열을 차지하는데 7열에서는 필드 밖으로 나간다
            f"[{SUMMON_SKILL_ID}/7열/에너미_3]",
            # 열이 없다
            f"[{SUMMON_SKILL_ID}/에너미_1]",
            # 이름이 없다
            f"[{SUMMON_SKILL_ID}/3열]",
        ],
    )
    def test_invalid_summon_rejects_the_whole_command(self, text):
        ctx, manager = _setup()

        with pytest.raises(CommandValidationError):
            _declare(ctx, manager, text)

        assert ctx.characters[SUMMONER].status.remaining_cost == 3
        assert SUMMONED not in ctx.characters

    def test_full_column_rejects_the_summon(self):
        ctx, manager = _setup()
        for i in range(CHARACTER_PER_COLUMN):
            ctx.add_character(
                get_test_preset(f"적군_{i}"),
                FactionType.ENEMY,
                BattlefieldColumnIndex(2),
            )

        with pytest.raises(CommandValidationError, match="소환할 수 없습니다"):
            _declare(ctx, manager, f"[{SUMMON_SKILL_ID}/3열/에너미_1]")

    def test_same_enemy_twice_in_one_command_is_rejected(self):
        ctx, manager = _setup()

        with pytest.raises(CommandValidationError):
            _declare(
                ctx,
                manager,
                f"[{SUMMON_SKILL_ID}/3열/에너미_1 - {SUMMON_SKILL_ID}/4열/에너미_1]",
            )

        assert SUMMONED not in ctx.characters

    def test_context_without_roster_cannot_summon(self):
        ctx, manager = _setup()
        ctx.summon_roster_source = dict

        with pytest.raises(CommandValidationError, match="찾을 수 없습니다"):
            _declare(ctx, manager, f"[{SUMMON_SKILL_ID}/3열/에너미_1]")
