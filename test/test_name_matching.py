import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

from battle.core.battlefield_context import BattlefieldContext  # noqa: E402
from battle.core.commands.admin import ChangePhaseCommand  # noqa: E402
from battle.core.commands.define import RoundPhaseType  # noqa: E402
from battle.core.commands.parser import parse_character_command  # noqa: E402
from battle.core.round_manager import RoundManager  # noqa: E402
from battle.objects.define import (  # noqa: E402
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.item.models import ItemData  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectHeal  # noqa: E402
from battle.objects.skill.models import SkillData  # noqa: E402
from bot.commands import admin as admin_module  # noqa: E402
from bot.commands import noncombat as noncombat_module  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from spreadsheets.inventory import Inventory  # noqa: E402
from utils.name_matching import (  # noqa: E402
    find_matching_key,
    normalize_name,
    resolve_matching_key,
    whitespace_tolerant_literal,
)


# ── 유틸리티 단위 테스트 ─────────────────────────────────────────────────────


def test_normalize_name_removes_all_whitespace():
    assert normalize_name("변칙 공격") == "변칙공격"
    assert normalize_name("적  군   1") == "적군1"
    assert normalize_name("강타") == "강타"


def test_resolve_matching_key_prefers_exact_match():
    assert resolve_matching_key("변칙 공격", ["변칙 공격", "변칙공격"]) == "변칙 공격"


def test_resolve_matching_key_falls_back_to_normalized_match():
    assert resolve_matching_key("변칙공격", ["강타", "변칙 공격"]) == "변칙 공격"
    assert resolve_matching_key("적군1", ["적군 1", "적군 2"]) == "적군 1"


def test_resolve_matching_key_returns_raw_when_no_match():
    assert resolve_matching_key("존재하지않음", ["강타", "변칙 공격"]) == "존재하지않음"


def test_find_matching_key_returns_none_when_no_match():
    assert find_matching_key("존재하지않음", ["강타"]) is None
    assert find_matching_key("변칙공격", ["변칙 공격"]) == "변칙 공격"


def test_whitespace_tolerant_literal_matches_any_internal_spacing():
    import re

    pattern = re.compile(whitespace_tolerant_literal("페이즈"))
    assert pattern.fullmatch("페이즈")
    assert pattern.fullmatch("페 이 즈")
    assert pattern.fullmatch("페이 즈")


# ── 전투 커맨드 파이프라인 통합 테스트 ────────────────────────────────────────


def _ally_action_manager(ctx) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


def test_skill_and_target_name_ignore_whitespace_differences():
    """스킬명과 대상명에 등록된 표기와 다른 공백을 넣어도 정상 처리되어야 한다."""
    skill = SkillData(
        id="변칙 공격",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None)
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"변칙 공격": skill})
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="변칙 공격"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0))

    # 스킬명·대상명 모두 공백을 빼고 입력
    cmd = parse_character_command(CharacterId("아군 1"), "[변칙공격/적군1]", ctx)
    manager.process_command(cmd)

    assert ctx.characters[CharacterId("적군 1")].status.curr_hp == 90


def test_attack_target_name_with_extra_whitespace_resolves():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = _ally_action_manager(ctx)
    ctx.add_character(get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0))

    cmd = parse_character_command(CharacterId("아군 1"), "[공격/적군   1]", ctx)
    manager.process_command(cmd)

    assert ctx.characters[CharacterId("적군 1")].status.curr_hp < 100


def test_item_name_and_target_ignore_whitespace_differences():
    item = ItemData(
        id="폭탄",
        target_rule="SkillTargetRuleNamed",
        cost=1,
        attack_range=1,
        effect=SkillEffectHeal(ValueSourceType.FIXED, 20, ValueType.INTEGER, None, None),
    )
    ctx = BattlefieldContext(
        buff_dict={},
        skill_dict={},
        item_dict={"폭탄": item},
        inventory=Inventory({("아군 1", "폭탄"): 1}),
    )
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1", initial_hp=50), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    cmd = parse_character_command(CharacterId("아군 1"), "[폭탄]", ctx)
    manager.process_command(cmd)

    assert ctx.characters[CharacterId("아군 1")].status.curr_hp == 70


# ── 커맨드 키워드 공백 허용 테스트 ────────────────────────────────────────────


def test_admin_keyword_regexes_ignore_internal_whitespace():
    assert admin_module._RE_BATTLE_PREP.search("[전 투 준 비]")
    assert admin_module._RE_BATTLE_START.search("[전투  개시]")
    assert admin_module._RE_PHASE.search("[진 행]")
    assert admin_module._RE_CONTINUE.search("[전투속행]")
    assert admin_module._RE_END.search("[전투 종 료]")
    assert admin_module._RE_INVESTIGATION_BATTLE.search("[상 시 전 투]")
    assert admin_module._RE_PRACTICE_PREP.search("[대 련]")


def test_noncombat_keyword_regexes_ignore_internal_whitespace():
    assert noncombat_module._RE_ROLL.search("[판 정/육체]")
    assert noncombat_module._RE_USE_ITEM.search("[사 용/포션]")
    assert noncombat_module._RE_TRANSFER_ITEM.search("[양 도/포션/동료]")


def test_manual_place_resolves_name_with_whitespace_mismatch(monkeypatch):
    """[배치/이름/진영 열]에서 이름의 공백이 등록명과 달라도 대상을 찾아야 한다."""

    class _FakeSession:
        started = False

    class _FakeState:
        session = _FakeSession()
        name_dict = {"변칙 늑대": object()}
        pending_placements: list = []

    result = admin_module._cmd_manual_place("변칙늑대", "아군 3열", _FakeState())
    assert "찾을 수 없습니다" not in result
    assert _FakeState.pending_placements[0][0] == "변칙 늑대"
