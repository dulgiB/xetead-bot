import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.core.battlefield_context import BattlefieldContext  # noqa: E402
from battle.core.commands.admin import ChangePhaseCommand  # noqa: E402
from battle.core.commands.define import RoundPhaseType  # noqa: E402
from battle.core.commands.parser import parse_character_command  # noqa: E402
from battle.core.round_manager import RoundManager  # noqa: E402
from battle.exceptions import CommandValidationError  # noqa: E402
from battle.objects.define import (  # noqa: E402
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId  # noqa: E402
from battle.objects.skill.effects import SkillEffectDamage  # noqa: E402
from battle.objects.skill.models import SkillData  # noqa: E402
from bot.commands import admin as admin_module  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from spreadsheets.models.combat import (  # noqa: E402
    CombatCharacterDataFromSpreadsheet,
    parse_name_aliases,
    resolve_sheet_character_name,
)
from utils.name_matching import find_name_or_alias  # noqa: E402

import pytest  # noqa: E402

# ── 시트 값 파싱 ──────────────────────────────────────────────────────────────


def test_parse_name_aliases_splits_on_comma():
    assert parse_name_aliases("늑대, 회색 늑대 ,늑대,") == ("늑대", "회색 늑대")
    assert parse_name_aliases("") == ()
    assert parse_name_aliases(None) == ()
    # 숫자만 적힌 셀은 get_all_records가 int로 돌려준다.
    assert parse_name_aliases(7) == ("7",)


def test_from_dict_reads_optional_name_alias_column():
    row = {
        "name": "대상_1",
        "mastodon_id": "",
        "curr_hp": 10,
        "max_hp": 10,
        "atk": 1,
        "attack_range": 1,
        "m_res": "보통",
        "is_magic": False,
        "max_cost": 3,
    }
    assert CombatCharacterDataFromSpreadsheet.from_dict(row).name_aliases == ()
    row["name_alias"] = "별명_1,별명_2"
    assert CombatCharacterDataFromSpreadsheet.from_dict(row).name_aliases == (
        "별명_1",
        "별명_2",
    )


# ── 이름/별명 해석 규칙 ───────────────────────────────────────────────────────


def test_find_name_or_alias_matches_alias_ignoring_whitespace():
    names = {"대상_1": ("회색 늑대",), "대상_2": ()}
    assert find_name_or_alias("회색늑대", names) == "대상_1"
    assert find_name_or_alias("없는이름", names) is None


def test_find_name_or_alias_prefers_real_name_over_alias():
    names = {"대상_1": ("대상_2",), "대상_2": ()}
    assert find_name_or_alias("대상_2", names) == "대상_2"


def test_find_name_or_alias_rejects_shared_alias():
    names = {"대상_1": ("늑대",), "대상_2": ("늑대",)}
    assert find_name_or_alias("늑대", names) is None


def test_resolve_sheet_character_name_uses_aliases():
    name_dict = {"대상_1": get_test_preset("대상_1", name_aliases=("별명_1",))}
    assert resolve_sheet_character_name("별명_1", name_dict) == "대상_1"
    assert resolve_sheet_character_name("모름", name_dict) == "모름"


# ── 전투 커맨드 파이프라인 ────────────────────────────────────────────────────


def _ally_action_manager(ctx) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


def _context_with_skill() -> BattlefieldContext:
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=1,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None)
        ],
        description="",
    )
    return BattlefieldContext(buff_dict={}, skill_dict={"스킬_1": skill})


def test_attack_by_alias_hits_that_character():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1", name_aliases=("늑대",)),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )

    manager.process_command(
        parse_character_command(CharacterId("아군 1"), "[공격/늑대]", ctx)
    )

    assert ctx.characters[CharacterId("적군 1")].status.curr_hp < 100


def test_skill_by_alias_records_real_name_as_target():
    ctx = _context_with_skill()
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="스킬_1"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1", name_aliases=("회색 늑대",)),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )

    cmd = parse_character_command(CharacterId("아군 1"), "[스킬_1/회색늑대]", ctx)
    manager.process_command(cmd)

    assert ctx.characters[CharacterId("적군 1")].status.curr_hp == 90
    # 이후 단계(답글·POST 재전개)가 실제 이름을 보도록 커맨드 자체가 치환된다.
    assert cmd.parts[0].targets == [CharacterId("적군 1")]


def test_shared_alias_on_field_is_not_found():
    ctx = _context_with_skill()
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="스킬_1"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    for name in ("적군 1", "적군 2"):
        ctx.add_character(
            get_test_preset(name, name_aliases=("늑대",)),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

    cmd = parse_character_command(CharacterId("아군 1"), "[스킬_1/늑대]", ctx)
    with pytest.raises(CommandValidationError):
        manager.process_command(cmd)
    assert ctx.characters[CharacterId("적군 1")].status.curr_hp == 100
    assert ctx.characters[CharacterId("적군 2")].status.curr_hp == 100


def test_alias_shared_with_off_field_character_still_resolves():
    """별명 충돌은 전장에 있는 캐릭터끼리만 본다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("적군 1", name_aliases=("늑대",)),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    assert ctx.resolve_character_id(CharacterId("늑대")) == CharacterId("적군 1")


def test_refresh_character_data_updates_aliases():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.refresh_character_data(
        CharacterId("적군 1"), get_test_preset("적군 1", name_aliases=("늑대",))
    )
    assert ctx.resolve_character_id(CharacterId("늑대")) == CharacterId("적군 1")


# ── 설정 경고 ─────────────────────────────────────────────────────────────────


def test_name_alias_problems_reports_unusable_aliases():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("적군 1", name_aliases=("늑대", "적군 2", "a/b", "3열")),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 2", name_aliases=("늑 대",)),
        FactionType.ENEMY,
        BattlefieldColumnIndex(1),
    )

    problems = ctx.name_alias_problems()

    assert any("'a/b'" in p and "커맨드 기호" in p for p in problems)
    assert any("'적군 2'" in p and "이름과 같아" in p for p in problems)
    assert any("'3열'" in p and "열 번호" in p for p in problems)
    assert any("'늑대'" in p and "적군 1, 적군 2" in p for p in problems)
    assert len(problems) == 4


def test_name_alias_problems_empty_without_conflicts():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("적군 1", name_aliases=("늑대",)),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    assert ctx.name_alias_problems() == []


# ── 봇 계층 ───────────────────────────────────────────────────────────────────


def test_manual_place_resolves_alias():
    class _FakeSession:
        started = False

    class _FakeState:
        session = _FakeSession()
        name_dict = {"대상_1": get_test_preset("대상_1", name_aliases=("별명_1",))}
        pending_placements: list = []

    result = admin_module._cmd_manual_place("별명_1", "적군 3열", _FakeState())
    assert result.ok
    assert _FakeState.pending_placements[0][0] == "대상_1"
