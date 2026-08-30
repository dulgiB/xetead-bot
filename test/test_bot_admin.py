import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

import contextlib
import itertools
from pathlib import Path

from battle.core.commands.define import RoundPhaseType  # noqa: E402
from battle.objects.buff.buff_base import BuffAddData  # noqa: E402
from battle.objects.buff.models import BuffData  # noqa: E402
from battle.objects.define import (  # noqa: E402
    BattlefieldColumnIndex,
    FactionType,
    ValueType,
)
from battle.objects.models import CharacterId  # noqa: E402
from battle.objects.skill.effects import SkillEffectAddBuff  # noqa: E402
from battle.objects.skill.models import SkillData  # noqa: E402
from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import PracticeRoundPhase, SideType  # noqa: E402
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot import log_sheets  # noqa: E402
from bot import main as main_module  # noqa: E402
from bot.commands import admin as admin_module  # noqa: E402
from bot.commands import character as character_module  # noqa: E402
from bot.commands.admin import (  # noqa: E402
    _cmd_advance_phase,
    _cmd_battle_start,
    _cmd_continue_battle,
)
from bot.main import BotState, MastodonBotListener, _handle_practice_command  # noqa: E402
from bot.noncombat_state import InvestigationSession  # noqa: E402
from bot.practice_state import PracticeBattleState  # noqa: E402
from bot.session import BattleSession  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from test_bot_noncombat import _quest, _quest_location  # noqa: E402
from test_load_battle_data import _base_sheets, _FakeSpreadsheet  # noqa: E402


def _make_state(**pending) -> BotState:
    state = BotState(
        char_dict={},
        name_dict={"유효 캐릭터": get_test_preset("유효 캐릭터")},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    state.session = BattleSession(buff_dict={}, skill_dict={})
    state.pending_placements = pending.get("pending_placements", [])
    state.pending_participants = pending.get("pending_participants", [])
    return state


def _only_practice(state: BotState) -> PracticeBattleState:
    """대부분의 테스트는 대련/상시전투 세션을 하나만 다루므로, 그 하나를
    state.practices(dict)에서 꺼내는 공용 헬퍼."""
    assert len(state.practices) == 1
    return next(iter(state.practices.values()))


def test_battle_does_not_start_when_all_placements_fail():
    """모든 배치가 실패(존재하지 않는 캐릭터 등)하면 전투가 시작되면 안 된다."""
    state = _make_state(
        pending_placements=[
            ("존재하지 않는 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )

    result = _cmd_battle_start(state)

    assert state.session.started is False
    assert len(state.session.context.characters) == 0
    assert "시작하지 못했습니다" in result.reply_text


def test_battle_starts_when_at_least_one_placement_succeeds():
    """일부 배치만 성공해도(캐릭터 1명 이상) 전투는 정상적으로 시작되어야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
            ("존재하지 않는 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(1)),
        ]
    )

    result = _cmd_battle_start(state)

    assert state.session.started is True
    assert len(state.session.context.characters) == 1
    assert "전투 시작" in result.reply_text


def test_battle_start_marks_round_start_for_field_image():
    """[전투개시]는 라운드 1 시작이므로 game_post에 필드 시트 이미지를 붙여야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )

    result = _cmd_battle_start(state)

    assert result.attach_field_image is True


def test_battle_start_blocked_and_retryable_for_broken_enemy_buff_timing():
    """'스킬_에너미' 시트에 buff_add_timing이 비어 있어 어느 페이즈에도 버프가
    적용될 수 없는 스킬이 있으면 전투가 시작되면 안 된다 — 그대로 시작되면
    그 버프가 실전에서 조용히 빠진 채 진행되고, 이미 배치·시작된 전투는
    되돌릴 수 없어 시트를 고쳐도 재시도가 안 된다. 대신 pending_placements가
    그대로 남아 있어 시트 수정 후 [전투개시]를 다시 입력하면 재시도할 수
    있어야 하고, 문제의 구체적인 내용은 admin_dm_text로만 전달되어야 하며
    공개 답글은 아예 남기지 않아야 한다(DM 알림만으로 충분하다)."""
    placements = [("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))]
    state = _make_state(pending_placements=list(placements))
    state.spreadsheet = _FakeSpreadsheet(
        _base_sheets(
            **{
                "스킬_에너미": [
                    {
                        "id": "고장난 스킬",
                        "target_rule": "SkillTargetRuleColumn",
                        "target_count": 1,
                        "cost": 1,
                        "effect_0": "SkillEffectAddBuff",
                        "value_type_0": "버프",
                        "buff_name_0": "디버프_1",
                        "description": "",
                    }
                ]
            }
        )
    )

    result = _cmd_battle_start(state)

    assert state.session.started is False
    assert len(state.session.context.characters) == 0
    assert state.pending_placements == placements  # 재시도를 위해 그대로 남아야 함
    assert result.admin_dm_text is not None
    assert "고장난 스킬" in result.admin_dm_text
    assert "디버프_1" in result.admin_dm_text
    assert result.reply_text == ""
    assert result.game_post_text is None

    # 시트를 고친 뒤(=이 fixture에서는 "정상 스킬"뿐인 새 스프레드시트로
    # 교체해 시뮬레이션) 같은 상태로 재시도하면 정상적으로 전투가 시작돼야 한다.
    state.spreadsheet = _FakeSpreadsheet(_base_sheets())
    retry_result = _cmd_battle_start(state)

    assert state.session.started is True
    assert retry_result.admin_dm_text is None


def test_battle_start_admin_dm_is_none_when_enemy_buff_timing_is_valid():
    """'스킬_에너미' 시트에 문제가 없으면 admin_dm_text가 비어 있어야 한다
    (매번 admin에게 DM이 가면 오히려 알림이 무의미해진다)."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    state.spreadsheet = _FakeSpreadsheet(
        _base_sheets(
            **{
                "스킬_에너미": [
                    {
                        "id": "정상 스킬",
                        "target_rule": "SkillTargetRuleColumn",
                        "target_count": 1,
                        "cost": 1,
                        "effect_0": "SkillEffectAddBuff",
                        "value_type_0": "버프",
                        "buff_name_0": "디버프_2",
                        "buff_add_timing_0": "적 행동 선언",
                        "description": "",
                    }
                ]
            }
        )
    )

    result = _cmd_battle_start(state)

    assert result.admin_dm_text is None
    assert state.session.started is True


def test_battle_start_reports_error_for_defeated_participant():
    """참전 신청자 중 체력이 0인 캐릭터는 무작위 자동 배치 중 예전에는
    조용히 사라졌다 — 이제는 오류로 보고되어 관리자가 알 수 있어야 하고,
    나머지 참전 신청자는 정상적으로 배치되어야 한다."""
    state = _make_state(pending_participants=["dead_acct", "alive_acct"])
    state.char_dict = {
        "dead_acct": get_test_preset("탈락캐릭터", initial_hp=0),
        "alive_acct": get_test_preset("생존캐릭터"),
    }

    result = _cmd_battle_start(state)

    assert state.session.started is True
    assert CharacterId("생존캐릭터") in state.session.context.characters
    assert CharacterId("탈락캐릭터") not in state.session.context.characters
    assert "탈락캐릭터" in result.reply_text


def test_battle_start_does_not_double_place_participant_who_was_also_manually_placed():
    """참전 신청(pending_participants)과 admin의 수동 배치(pending_placements)는
    서로 독립된 목록이라, 같은 캐릭터가 참전 신청도 하고 admin이 [배치/...]로도
    지정하면 예전에는 add_character()가 두 번 호출되어(기존 char_id 존재
    여부를 확인하지 않음) 같은 캐릭터가 두 칸을 동시에 차지했다 — 수동
    배치가 우선하고, 무작위 자동 배치에서는 제외되어야 한다."""
    state = _make_state(
        pending_placements=[("참가자", FactionType.ALLY, BattlefieldColumnIndex(2))],
        pending_participants=["참가자_acct"],
    )
    state.char_dict = {"참가자_acct": get_test_preset("참가자")}
    state.name_dict = {"참가자": get_test_preset("참가자")}

    _cmd_battle_start(state)

    char_id = CharacterId("참가자")
    assert char_id in state.session.context.characters
    occupied_columns = [
        col
        for col, slots in state.session.context.position_map[FactionType.ALLY].items()
        if char_id in slots.values()
    ]
    assert occupied_columns == [BattlefieldColumnIndex(2)]


def test_advance_phase_system_error_is_generic_and_logged(monkeypatch, caplog):
    """스프레드시트 저장/렌더링 실패는 원본 예외 메시지 대신 통일된
    "◊ 시스템 오류입니다."로만 노출되고, 전체 트레이스는 서버 로그에
    남아야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 API 내부 세부사항")

    monkeypatch.setattr(admin_module, "upsert_field_row", _boom)

    import logging

    with caplog.at_level(logging.ERROR, logger="bot.commands.admin"):
        result = _cmd_advance_phase(state)

    assert "◊ 시스템 오류입니다." in result.reply_text
    assert "시트 API 내부 세부사항" not in result.reply_text
    assert any(
        "필드 시트 저장 실패" in record.message and record.exc_info is not None
        for record in caplog.records
    )


def test_advance_phase_always_marks_field_image():
    """필드 현황은 str 대신 이미지로만 표시하므로, 모든 페이즈 전환
    게시물(ALLY_ACTION, ENEMY_POST_ACTION, STANDBY 진입 모두)에 이미지를
    붙여야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)

    to_ally_action = _cmd_advance_phase(state)
    to_enemy_post_action = _cmd_advance_phase(state)
    to_standby = _cmd_advance_phase(state)

    assert to_ally_action.attach_field_image is True
    assert to_enemy_post_action.attach_field_image is True
    assert to_standby.attach_field_image is True


def test_enemy_post_action_summary_includes_calculation(monkeypatch):
    """적 공격 정산(ENEMY_POST_ACTION) 게시물의 계산식은 본문(game_post_text)이
    아니라 별도의 CW 후속 게시물용 game_post_calc_text로 분리돼야 한다 —
    본문(+필드 시트 이미지)은 항상 짧고 바로 보이게 남겨야 하기 때문이다.
    어느 적이 한 행동인지는 본문에 표시하지 않는다 — 여러 적의 결과를 한
    게시물에 모아 보여주므로, 필요하면 계산식(CW 후속 게시물, 이름이
    붙어 있다)을 펼쳐서 확인하면 된다."""
    monkeypatch.setattr(
        log_sheets, "_load_hp_write_targets", lambda spreadsheet, cache=None: {}
    )
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터")
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    _cmd_battle_start(state)

    admin_module._cmd_proxy("적 캐릭터", "[공격/유효 캐릭터]", state)

    _cmd_advance_phase(state)  # → 아군 행동
    to_post_action = _cmd_advance_phase(state)  # → 적 공격 정산

    assert "1d6" not in to_post_action.game_post_text
    assert "적 캐릭터" not in to_post_action.game_post_text
    assert "1d6" in to_post_action.game_post_calc_text
    assert "적 캐릭터" in to_post_action.game_post_calc_text


def test_enemy_post_action_summary_merges_damage_to_same_target_across_attackers(
    monkeypatch,
):
    """서로 다른 적 여러 기가 같은 아군을 각각 공격하면, 본문(game_post_text)에는
    공격자마다 별도 줄이 아니라 그 아군에 대한 대미지 합계 한 줄로 합쳐져야
    한다 — 개별 커맨드 답글의 spoiler_text 요약과 동일한 방식으로, 적이
    많아져도 본문이 늘어지지 않게 하기 위함이다."""
    monkeypatch.setattr(
        log_sheets, "_load_hp_write_targets", lambda spreadsheet, cache=None: {}
    )
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적1"] = get_test_preset("적1")
    state.name_dict["적2"] = get_test_preset("적2")
    state.pending_placements.append(
        ("적1", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    state.pending_placements.append(
        ("적2", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    _cmd_battle_start(state)

    admin_module._cmd_proxy("적1", "[공격/유효 캐릭터]", state)
    admin_module._cmd_proxy("적2", "[공격/유효 캐릭터]", state)

    _cmd_advance_phase(state)  # → 아군 행동
    to_post_action = _cmd_advance_phase(state)  # → 적 공격 정산

    body = to_post_action.game_post_text
    assert body.count("유효 캐릭터 |") == 1


def test_long_game_post_text_splits_into_thread_instead_of_truncating():
    """game_post_text(적군 행동 정산 완료 등)가 500자를 넘으면 truncate로
    뒷부분을 잘라내지 않고, 계산식(_post_calc_followups)과 동일하게 줄
    단위로 나눈 여러 게시물을 서로 답글로 이어붙인 스레드로 보내야 한다."""
    state = _make_state()
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    lines = [f"▹ 캐릭터{i} | -10 → 90/100" for i in range(30)]
    long_text = "\n".join(lines)
    assert len(long_text) > 500  # 실제로 분할이 필요한 길이인지 확인

    result = admin_module.AdminCommandResult(
        reply_text="◊ [라운드 1] 적군 행동 정산 완료", game_post_text=long_text
    )
    listener._post_admin_result(result, 1, "test-admin", "public", state)

    game_post_calls = mastodon.status_post_calls[1:]  # [0]은 reply_text 확인 답글
    assert len(game_post_calls) > 1
    for call in game_post_calls:
        assert len(call["status"]) <= 500
    for i in range(1, len(game_post_calls)):
        assert "in_reply_to_id" in game_post_calls[i]
    reconstructed = "\n".join(call["status"] for call in game_post_calls)
    assert reconstructed == long_text


def test_enemy_post_action_summary_lists_unique_granted_buff_info(monkeypatch):
    """적 공격 정산 게시물 하단에는 이번 정산에서 새로 부여된 버프의 설명을
    "**【버프 정보】**\n▹ [버프id]: 설명" 형식으로 모아 보여줘야 한다. 같은
    버프(열 광역기로 두 명에게 동시에 부여)가 여러 명에게 적용돼도 설명은
    buff_id 기준으로 한 번만 나와야 한다."""
    monkeypatch.setattr(
        log_sheets, "_load_hp_write_targets", lambda spreadsheet, cache=None: {}
    )
    buff = BuffData(
        id="테스트디버프",
        buff_class_name="BuffReceivedDamage",
        duration_turn_value=2,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=15,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="받는 대미지가 15% 증가한다.",
    )
    skill = SkillData(
        id="마킹",
        target_rule="SkillTargetRuleColumn",
        target_count=1,
        cost=1,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id="테스트디버프",
                buff_add_timing=RoundPhaseType.ENEMY_POST_ACTION,
            )
        ],
        description="",
    )
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
            ("유효 캐릭터2", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["유효 캐릭터2"] = get_test_preset("유효 캐릭터2")
    state.session = BattleSession(
        buff_dict={"테스트디버프": buff}, skill_dict={"마킹": skill}
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터", skill_1_id="마킹")
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    _cmd_battle_start(state)

    admin_module._cmd_proxy("적 캐릭터", "[마킹/1열]", state)

    _cmd_advance_phase(state)  # → 아군 행동
    to_post_action = _cmd_advance_phase(state)  # → 적 공격 정산

    assert to_post_action.game_post_text.count("**【버프 정보】**") == 1
    assert (
        to_post_action.game_post_text.count(
            "▹ [테스트디버프]: 받는 대미지가 15% 증가한다."
        )
        == 1
    )


def test_advance_phase_writes_back_post_action_damage(monkeypatch):
    """적 공격 정산(ENEMY_POST_ACTION) 시 발생한 대미지도 "캐릭터" 시트에
    반영되어야 한다 — 이전에는 개별 캐릭터 커맨드/프록시에서만 write-back이
    호출되고 POST_ACTION 정산 자체는 반영되지 않는 갭이 있었다."""

    class _RecordingWorksheet:
        def __init__(self, row_to_name: dict[int, str]):
            self._row_to_name = row_to_name
            self.recorded_hp: dict = {}

        def update_cell(self, row, col, value):
            self.recorded_hp[self._row_to_name[row]] = value

    ws = _RecordingWorksheet({2: "유효 캐릭터", 3: "적 캐릭터"})
    monkeypatch.setattr(
        log_sheets,
        "_load_hp_write_targets",
        lambda spreadsheet, cache=None: {
            "유효 캐릭터": (ws, 2, 1),
            "적 캐릭터": (ws, 3, 1),
        },
    )
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터")
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    _cmd_battle_start(state)

    admin_module._cmd_proxy("적 캐릭터", "[공격/유효 캐릭터]", state)

    _cmd_advance_phase(state)  # → 아군 행동
    _cmd_advance_phase(state)  # → 적 공격 정산

    assert "유효 캐릭터" in ws.recorded_hp


def test_proxy_repeated_attacks_on_same_target_merge_into_one_summary_line():
    """프록시(관리자 대행)로 같은 대상을 여러 번 공격해도(예: [공격/대상 -
    공격/대상 - 공격/대상]) 답글 요약에는 체력 변화가 합산된 한 줄로만
    보여야 한다 — 프록시 경로는 파트를 하나씩 잘라 개별 블록으로 조립하므로
    (_format_named_reply), 직접 커맨드 경로와 별도로 확인해야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터", max_hp=500)
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    _cmd_battle_start(state)
    _cmd_advance_phase(state)  # → 아군 행동

    reply_text, _calc_text, _battle_log = admin_module._cmd_proxy(
        "유효 캐릭터", "[공격/적 캐릭터 - 공격/적 캐릭터 - 공격/적 캐릭터]", state
    )

    target = state.session.context.characters[CharacterId("적 캐릭터")]
    total_damage = 500 - target.status.curr_hp
    assert reply_text == (
        f"유효 캐릭터 ▹ 적 캐릭터 | -{total_damage} → {target.status.curr_hp}/500"
    )


def test_proxy_pre_action_reply_prefixes_each_part_with_caster_name():
    """관리자 프록시로 대행한 PRE 선언 답글도 POST 정산과 마찬가지로,
    CommandPart(파트)별 결과 줄(또는, 아직 결과가 없는 파트라면 헤더) 앞에
    대행한 캐릭터의 이름이 붙어야 한다 — 답글 자체만으로는 누가 행동했는지
    알 수 없기 때문이다. 공격의 대미지는 POST에서 정산되므로 PRE 선언
    답글에는 결과 줄이 없어 헤더가 그대로 남는다. 단, 이동처럼 결과 줄이
    이미 "▹ {이름} | ..."로 캐릭터 이름을 보여주는 경우(대상이 항상 시전자
    자신)는 앞에 이름을 또 붙이면 중복이라 접두어를 생략한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터")
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    _cmd_battle_start(state)

    reply_text, _calc_text, _battle_log = admin_module._cmd_proxy(
        "적 캐릭터", "[이동/3열 - 공격/유효 캐릭터]", state
    )

    assert reply_text == (
        "▹ 적 캐릭터 | 3열로 이동\n\n적 캐릭터 **【공격 ▸ 유효 캐릭터】**"
    )


def test_handle_admin_command_processes_multiple_proxy_commands_in_one_message():
    """상시전투/DM전투 배치가 이미 한 메시지에 여러 [배치/...]를 받아들이는
    것처럼, 프록시 커맨드도 줄바꿈으로 구분된 여러 "◊ 이름 [커맨드]"를
    한 메시지에서 모두 처리해야 한다 — 적마다 매번 별도 게시물을 보내는
    번거로움을 없애기 위함."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적1"] = get_test_preset("적1")
    state.name_dict["적2"] = get_test_preset("적2")
    state.pending_placements.append(
        ("적1", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    state.pending_placements.append(
        ("적2", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    _cmd_battle_start(state)

    result = admin_module.handle_admin_command(
        "◊ 적1 [공격/유효 캐릭터]\n◊ 적2 [공격/유효 캐릭터]", state
    )

    assert "적1" in result.reply_text
    assert "적2" in result.reply_text
    assert len(result.battle_logs) == 2


def test_manual_place_accepts_multiple_placements_in_one_message():
    """[배치/...]도 프록시 커맨드와 마찬가지로 한 메시지에 여러 개를 줄바꿈으로
    함께 보내면 전부 pending_placements에 등록되고, 답글은 "◊ 수동 배치: " 뒤에
    성공한 배치를 쉼표로 이어붙인 한 줄로 합쳐져야 한다(적이 많아져도 답글이
    줄 단위로 늘어나 500자 제한에 걸리지 않도록)."""
    state = _make_state()
    state.name_dict["적1"] = get_test_preset("적1")
    state.name_dict["적2"] = get_test_preset("적2")

    result = admin_module.handle_admin_command(
        "[배치/적1/적군 1열]\n[배치/적2/적군 2열]", state
    )

    assert result.reply_text == "◊ 수동 배치: 적1(적군 1열), 적2(적군 2열)"
    assert state.pending_placements == [
        ("적1", FactionType.ENEMY, BattlefieldColumnIndex.from_str("1")),
        ("적2", FactionType.ENEMY, BattlefieldColumnIndex.from_str("2")),
    ]


def test_manual_place_reports_errors_separately_from_successes():
    """일부 배치는 성공하고 일부는 실패하면, 성공은 "◊ 수동 배치: ..." 한 줄로
    모으고 실패는 각자의 오류 메시지를 별도 줄로 유지해야 한다."""
    state = _make_state()
    state.name_dict["적1"] = get_test_preset("적1")

    result = admin_module.handle_admin_command(
        "[배치/적1/적군 1열]\n[배치/존재하지 않는 캐릭터/적군 2열]", state
    )

    lines = result.reply_text.split("\n")
    assert lines[0] == "◊ 수동 배치: 적1(적군 1열)"
    assert "존재하지 않는 캐릭터" in lines[1]
    assert "찾을 수 없습니다" in lines[1]


def test_continue_battle_marks_round_start_for_field_image():
    """[전투속행]은 다음 라운드 시작(ENEMY_PRE_ACTION 진입)이므로 이미지를
    붙여야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)
    for _ in range(3):  # ALLY_ACTION → ENEMY_POST_ACTION → STANDBY
        _cmd_advance_phase(state)

    result = _cmd_continue_battle(state)

    assert result.attach_field_image is True


def test_manual_place_blocked_during_ally_action_phase():
    """전투가 이미 시작되어 라운드 종료(다음 라운드 대기) 단계가 아니면
    [배치/...]는 여전히 막혀야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)
    _cmd_advance_phase(state)  # ENEMY_PRE_ACTION → ALLY_ACTION
    assert state.session.current_phase == RoundPhaseType.ALLY_ACTION

    state.name_dict["증원"] = get_test_preset("증원")
    result = admin_module.handle_admin_command("[배치/증원/적군 1열]", state)

    assert "증원" not in state.session.context.characters
    assert "라운드 종료" in result.reply_text


def test_manual_place_allowed_during_next_round_standby_before_continue():
    """라운드 종료(다음 라운드 대기) 단계에서는 [전투 속행] 입력 전에
    [배치/...]로 증원을 즉시 전장에 배치할 수 있어야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)
    for _ in range(3):  # ALLY_ACTION → ENEMY_POST_ACTION → STANDBY
        _cmd_advance_phase(state)
    assert (
        state.session.current_phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY
    )

    state.name_dict["증원"] = get_test_preset("증원")
    result = admin_module.handle_admin_command("[배치/증원/적군 1열]", state)

    assert result.reply_text == "◊ 수동 배치: 증원(적군 1열)"
    added = state.session.context.characters[CharacterId("증원")]
    assert added.faction == FactionType.ENEMY


def test_investigation_battle_inline_placement_respects_faction_token(monkeypatch):
    """[상시전투]와 함께 입력된 [배치/이름/아군 3열]은 '아군' 토큰대로
    SIDE_1(아군)에 배치되어야 하며, 무조건 적(SIDE_2)으로 배치되면 안 된다."""
    state = _make_state()
    state.name_dict = {"동료": get_test_preset("동료")}
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )

    result = admin_module._cmd_investigation_battle(
        "[상시전투][배치/동료/아군 3열]", [], state
    )

    assert not result.reply_text or "오류" not in (result.game_post_text or "")
    char_id = CharacterId("동료")
    ps = result.practice_to_register
    assert ps is not None
    assert char_id in ps.context.characters
    assert ps.context.get_side(char_id) == SideType.SIDE_1


def test_investigation_battle_with_inline_enemy_placement_is_not_routed_to_manual_place(
    monkeypatch,
):
    """[상시전투]와 [배치/이름/적군 열]을 같은 멘션에 함께 보내는 건
    README에 문서화된 정상 사용법이다 — 그런데 handle_admin_command의
    분기 순서상 본 전투용 [배치/...] 처리(_RE_MANUAL_PLACE)가 상시전투
    분기(_RE_INVESTIGATION_BATTLE)보다 먼저 검사되면, 이 메시지가 본
    전투용 수동 배치로 잘못 라우팅되어 session이 없다는 이유로
    "진행 중인 전투가 없습니다" 오류가 나고 상시전투 자체는 시작되지
    않는다. 이 테스트는 handle_admin_command를 실제로 거쳐서(직접
    _cmd_investigation_battle을 호출하지 않고) 그 라우팅 버그를 잡는다."""
    state = _make_state()
    state.session = None  # 실제 버그 재현 조건: [전투 준비]를 한 적 없는 상태
    state.name_dict = {"몬스터": get_test_preset("몬스터")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[상시전투][배치/몬스터/적군 4열]",
            extra_mentions=["ally_acct"],
        )
    )

    assert state.practices
    assert state.session is None  # 본 전투 세션으로 잘못 새지 않았어야 한다
    reply = mastodon.status_post_calls[-1]
    assert "진행 중인 전투가 없습니다" not in reply["status"]
    char_id = CharacterId("몬스터")
    ps = _only_practice(state)
    assert char_id in ps.context.characters
    assert ps.context.get_side(char_id) == SideType.SIDE_2


class _FakeMastodon:
    def __init__(self, ancestors: list[dict] | None = None):
        self._next_id = itertools.count(9000)
        self._next_media_id = itertools.count(1000)
        self.media_post_calls: list[str] = []
        self.status_post_calls: list[dict] = []
        self.last_media_id: int = 0
        # _thread_participants()가 조회하는 스레드 조상 목록 — 기본값(빈
        # 목록)은 "스레드 히스토리 없음"과 동일해 기존 테스트 동작을
        # 그대로 보존한다. 스레드 참여자 수집을 검증하는 테스트만 채워
        # 넣으면 된다.
        self.status_context_ancestors: list[dict] = ancestors or []

    def status_post(self, *args, **kwargs):
        if args:
            kwargs = {**kwargs, "status": args[0]}
        self.status_post_calls.append(kwargs)
        return {"id": next(self._next_id)}

    def media_post(self, media_file, *args, **kwargs):
        self.media_post_calls.append(str(media_file))
        self.last_media_id = next(self._next_media_id)
        return {"id": self.last_media_id}

    def status_context(self, status_id):
        return {"ancestors": self.status_context_ancestors, "descendants": []}


def _make_notification(
    acct: str,
    status_id: int,
    in_reply_to_id: int,
    text: str,
    visibility: str = "public",
    extra_mentions: list[str] | None = None,
) -> dict:
    mentions = [{"acct": "bot"}] + [{"acct": a} for a in (extra_mentions or [])]
    return {
        "type": "mention",
        "account": {"acct": acct},
        "status": {
            "id": status_id,
            "content": f"<p>@bot {text}</p>",
            "visibility": visibility,
            "in_reply_to_id": in_reply_to_id,
            "mentions": mentions,
        },
    }


def test_replying_again_to_stale_prep_post_does_not_restart_battle(monkeypatch):
    """포지션 선언이 완료되어 전투가 시작된 뒤, 같은 참가자가 실수로 원본
    준비 게시물에 다시 답글을 달아도 전투가 재시작되면 안 된다."""
    state = _make_state()
    state.char_dict = {"user1": get_test_preset("동료")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )

    context = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    manager = PracticeRoundManager(context)
    ps = PracticeBattleState(
        context=context,
        manager=manager,
        is_investigation=True,
        expected_accts=["user1"],
        prep_post_id=1000,
    )
    state.practices[1000] = ps

    listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

    listener.on_notification(_make_notification("user1", 1, 1000, "[아군/1열]"))

    assert ps.prep_post_id == 0
    assert len(ps.context.characters) == 1
    round_n_after_start = ps.round_n

    # 같은 참가자가 이미 소모된 원본 준비 게시물(1000)에 다시 답글
    listener.on_notification(_make_notification("user1", 2, 1000, "[아군/2열]"))

    assert len(ps.context.characters) == 1
    assert ps.round_n == round_n_after_start


def test_battle_prep_posts_as_new_status_not_reply(monkeypatch):
    """[전투준비] 공지는 답글이 아니라 타임라인의 새 게시물로 올라가야 하고,
    이후 참가 신청 답글이 그 게시물을 정상적으로 대상 삼을 수 있어야 한다."""
    state = _make_state()
    state.session = None
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[전투준비]"))

    assert len(mastodon.status_post_calls) == 1
    prep_call = mastodon.status_post_calls[0]
    assert "in_reply_to_id" not in prep_call
    assert "전투 준비" in prep_call["status"]

    prep_post_id = state.preparation_status_id
    state.char_dict["ally_acct"] = get_test_preset("유효 캐릭터")
    listener.on_notification(
        _make_notification("ally_acct", 2, prep_post_id, "아무 코멘트")
    )

    assert "ally_acct" in state.pending_participants


def test_malformed_notification_does_not_raise():
    """형식이 예상과 다른(status가 없는 등) 알림이 와도 예외가 밖으로
    전파되면 안 된다 — 스트리밍 리스너 전체가 죽는 것을 방지한다."""
    state = _make_state()
    listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

    listener.on_notification({"type": "mention", "account": {"acct": "user1"}})


@contextlib.contextmanager
def _fake_capture(spreadsheet, cache=None):
    yield Path("/tmp/fake-field.png")


def test_capture_field_media_ids_uploads_and_returns_media_id(monkeypatch):
    """캡처가 성공하면 업로드된 media_id를 리스트로 반환해야 한다."""
    state = _make_state()
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    media_ids = listener._capture_field_media_ids(state)

    assert media_ids == [mastodon.last_media_id]
    assert mastodon.media_post_calls == ["/tmp/fake-field.png"]


def test_capture_field_media_ids_absorbs_exception(monkeypatch):
    """캡처/업로드 실패는 예외를 흡수하고 빈 리스트를 반환해야 한다 —
    이 실패가 답글 전송 자체를 막으면 안 된다."""

    @contextlib.contextmanager
    def failing_capture(spreadsheet, cache=None):
        raise RuntimeError("network boom")
        yield  # pragma: no cover

    state = _make_state()
    monkeypatch.setattr(main_module, "capture_field_sheet_image", failing_capture)
    listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

    assert listener._capture_field_media_ids(state) == []


def test_round_start_game_post_attaches_field_image(monkeypatch):
    """[전투개시] 공개 게시물(라운드 시작 알림)에 필드 시트 이미지가 첨부되어야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[전투개시]"))

    public_posts = [c for c in mastodon.status_post_calls if "in_reply_to_id" not in c]
    assert len(public_posts) == 1
    assert public_posts[0]["media_ids"] == [mastodon.last_media_id]
    # 본 전투 페이즈 게시물은 visibility를 강제하지 않고 계정/서버 기본값을
    # 따라야 한다 — "public"으로 하드코딩하면 안 된다.
    assert "visibility" not in public_posts[0]


def test_character_command_reply_has_no_image_but_keeps_text(monkeypatch):
    """본 전투의 캐릭터 커맨드 답글은 이미지를 첨부하지 않고 텍스트만
    보내야 한다 — 필드 시트 이미지는 페이즈 게시물 전용이다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터")
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    state.char_dict["ally_acct"] = get_test_preset("유효 캐릭터")
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    monkeypatch.setattr(character_module, "write_back_changed_hp", lambda *a, **k: None)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[전투개시]"))
    listener.on_notification(_make_notification("test-admin", 2, 0, "[진행]"))
    active_post_id = state.active_phase_post_id

    listener.on_notification(
        _make_notification("ally_acct", 3, active_post_id, "[공격/적 캐릭터]")
    )

    # 계산식이 있으면 본문(요약)은 spoiler_text로, 계산식은 CW 처리된
    # status로 들어간 게시물 하나로 합쳐 보낸다.
    reply_calls = [c for c in mastodon.status_post_calls if "in_reply_to_id" in c]
    char_reply = reply_calls[-1]
    assert char_reply["media_ids"] is None
    assert "공격" in char_reply["status"]
    # 멘션 뒤에는 줄바꿈이 아니라 공백 하나만 두고 같은 줄에서 내용이
    # 이어져야 한다.
    assert char_reply["status"].startswith("@ally_acct ")


def test_character_command_reply_merges_calc_into_single_cw_post(monkeypatch):
    """계산식이 있는 커맨드 답글은 게시물 두 개(본문 + CW 후속)가 아니라,
    본문을 spoiler_text로, 계산식을 status로 넣은 게시물 하나로 합쳐
    보내야 한다. 계산식 줄 끝에는 최종 값("→ 값")이 붙어야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터")
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    state.char_dict["ally_acct"] = get_test_preset("유효 캐릭터")
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    monkeypatch.setattr(character_module, "write_back_changed_hp", lambda *a, **k: None)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[전투개시]"))
    listener.on_notification(_make_notification("test-admin", 2, 0, "[진행]"))
    active_post_id = state.active_phase_post_id

    before_calls = len(mastodon.status_post_calls)
    listener.on_notification(
        _make_notification("ally_acct", 3, active_post_id, "[공격/적 캐릭터]")
    )
    new_calls = mastodon.status_post_calls[before_calls:]

    # 계산식이 있는 답글은 게시물 하나로 끝나야 한다 (본문 + 별도 CW 후속
    # 게시물로 두 개가 되면 안 된다).
    assert len(new_calls) == 1
    call = new_calls[0]

    target = state.session.context.characters[CharacterId("적 캐릭터")]
    dealt = 100 - target.status.curr_hp
    assert call["spoiler_text"] == (
        f"▹ 적 캐릭터 | -{dealt} → {target.status.curr_hp}/100"
    )
    assert "↳" not in call["spoiler_text"]
    assert "@ally_acct" not in call["spoiler_text"]

    assert call["status"].startswith("@ally_acct ")
    assert "**【공격 ▸ 적 캐릭터】**" in call["status"]
    assert f"→ -{dealt}" in call["status"]


def test_main_battle_idle_chat_still_gets_error_reply(monkeypatch):
    """본 전투는 대련/DM 전투와 달리 페이즈마다 게시물이 새로 바뀌는
    구조라 스레드 하나가 계속 이어지지 않는다 — 사담을 조용히 무시하는
    대상이 아니므로, 대괄호 커맨드가 없으면 기존처럼 에러 답글을 보내야
    한다(silent_on_unrecognized 기본값이 False로 유지되는지 확인)."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.char_dict["ally_acct"] = get_test_preset("유효 캐릭터")
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[전투개시]"))
    listener.on_notification(_make_notification("test-admin", 2, 0, "[진행]"))
    active_post_id = state.active_phase_post_id

    listener.on_notification(
        _make_notification("ally_acct", 3, active_post_id, "화이팅!")
    )

    reply_calls = [c for c in mastodon.status_post_calls if "in_reply_to_id" in c]
    assert "인식할 수 없습니다" in reply_calls[-1]["status"]


def test_character_command_with_two_bracket_groups_is_rejected_with_explicit_error(
    monkeypatch,
):
    """캐릭터 계정이 대괄호를 두 개로 나눠 보내면(예: '[A] [B]'), 파서의 탐욕적
    매칭 때문에 하나만 조용히 처리되고 나머지가 사라지는 문제가 있었다 —
    본 전투 경로에서도 사전에 걸러 명시적 에러를 내야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터")
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    state.char_dict["ally_acct"] = get_test_preset("유효 캐릭터")
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    monkeypatch.setattr(character_module, "write_back_changed_hp", lambda *a, **k: None)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[전투개시]"))
    listener.on_notification(_make_notification("test-admin", 2, 0, "[진행]"))
    active_post_id = state.active_phase_post_id

    listener.on_notification(
        _make_notification(
            "ally_acct", 3, active_post_id, "[공격/적 캐릭터] [공격/적 캐릭터]"
        )
    )

    reply_calls = [c for c in mastodon.status_post_calls if "in_reply_to_id" in c]
    char_reply = reply_calls[-1]
    assert "대괄호 커맨드를 하나만" in char_reply["status"]


def test_ally_action_phase_post_attaches_field_image(monkeypatch):
    """필드 현황은 str 대신 이미지로만 표시하므로, 일반 페이즈 전환
    공개 게시물(아군 행동 등)에도 이미지가 붙어야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[진행]"))

    public_posts = [c for c in mastodon.status_post_calls if "in_reply_to_id" not in c]
    assert len(public_posts) == 1
    assert public_posts[0]["media_ids"] == [mastodon.last_media_id]


def test_phase_post_falls_back_to_text_board_when_image_capture_fails(monkeypatch):
    """이미지 캡처가 실패하면 게시물 텍스트에 str(context) 필드 보드를
    대체 표시해야 한다 (정보가 완전히 유실되면 안 되므로)."""

    @contextlib.contextmanager
    def _failing_capture(spreadsheet, cache=None):
        raise RuntimeError("capture boom")
        yield  # pragma: no cover

    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _failing_capture)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[진행]"))

    public_posts = [c for c in mastodon.status_post_calls if "in_reply_to_id" not in c]
    assert len(public_posts) == 1
    assert public_posts[0]["media_ids"] is None
    assert "유효 캐릭터" in public_posts[0]["status"]


def test_practice_session_posts_thread_together_with_matching_visibility(
    monkeypatch,
):
    """대련 세션의 모든 게시물은 최초 [대련] 개시 멘션의 visibility를 따르고,
    서로 답글로 이어져 하나의 스레드를 이뤄야 한다 — 매번 독립된 공개
    게시물로 흩어지면 안 된다. 대련은 Admin이 아니라 캐릭터 계정이 직접
    시작하는 명령어다."""
    state = _make_state()
    char_dict = {
        "swordsman_acct": get_test_preset("검사"),
        "archer_acct": get_test_preset("궁수"),
    }
    name_dict = {"검사": get_test_preset("검사"), "궁수": get_test_preset("궁수")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, name_dict, {}),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            char_dict,
            name_dict,
            {},
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "swordsman_acct",
            1,
            0,
            "[대련]",
            visibility="unlisted",
            extra_mentions=["archer_acct"],
        )
    )
    prep_call = mastodon.status_post_calls[-1]
    assert prep_call["visibility"] == "unlisted"
    assert prep_call["in_reply_to_id"] == 1
    prep_post_id = _only_practice(state).prep_post_id

    listener.on_notification(
        _make_notification("swordsman_acct", 2, prep_post_id, "[1팀/3열]")
    )
    listener.on_notification(
        _make_notification("archer_acct", 3, prep_post_id, "[2팀/5열]")
    )
    start_call = mastodon.status_post_calls[-1]
    assert start_call["visibility"] == "unlisted"
    assert start_call["in_reply_to_id"] == prep_post_id

    active_post_id = _only_practice(state).active_post_id
    first_acct, second_name = (
        ("swordsman_acct", "궁수")
        if _only_practice(state).first_mover.value == "1팀"
        else ("archer_acct", "검사")
    )
    calls_before_action = len(mastodon.status_post_calls)
    listener.on_notification(
        _make_notification(first_acct, 4, active_post_id, f"[공격/{second_name}]")
    )
    # 캐릭터의 커맨드 답글이 이 액션으로 발생하는 첫 번째 게시물이다 — 다음
    # 라운드 공지는 예전 라운드 공지(active_post_id)가 아니라 이 답글에
    # 이어져야 스레드가 갈라지지 않는다.
    char_reply_id = 9000 + calls_before_action
    round_call = mastodon.status_post_calls[-1]
    assert round_call["visibility"] == "unlisted"
    assert round_call["in_reply_to_id"] == char_reply_id
    assert round_call["in_reply_to_id"] != active_post_id


def test_practice_settlement_post_mentions_all_participants(monkeypatch):
    """정산(라운드 전환/종료) 게시물은 바로 위 답글(행동한 캐릭터의 커맨드
    응답)에 이어 붙는 별도 게시물이라, 명시적으로 멘션하지 않으면 방금
    행동한 사람 외의 참여자는 알림을 받지 못해 다음 턴 게시물을 놓칠 수
    있다 — 대련 참여자 전원이 멘션돼야 한다."""
    state = _make_state()
    char_dict = {
        "swordsman_acct": get_test_preset("검사"),
        "archer_acct": get_test_preset("궁수"),
    }
    name_dict = {"검사": get_test_preset("검사"), "궁수": get_test_preset("궁수")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, name_dict, {}),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            char_dict,
            name_dict,
            {},
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "swordsman_acct", 1, 0, "[대련]", extra_mentions=["archer_acct"]
        )
    )
    prep_post_id = _only_practice(state).prep_post_id

    listener.on_notification(
        _make_notification("swordsman_acct", 2, prep_post_id, "[1팀/3열]")
    )
    listener.on_notification(
        _make_notification("archer_acct", 3, prep_post_id, "[2팀/5열]")
    )

    active_post_id = _only_practice(state).active_post_id
    first_acct, second_name = (
        ("swordsman_acct", "궁수")
        if _only_practice(state).first_mover.value == "1팀"
        else ("archer_acct", "검사")
    )
    listener.on_notification(
        _make_notification(first_acct, 4, active_post_id, f"[공격/{second_name}]")
    )

    round_call = mastodon.status_post_calls[-1]
    assert "@swordsman_acct" in round_call["status"]
    assert "@archer_acct" in round_call["status"]


def test_practice_prep_includes_thread_ancestors_not_just_direct_mentions(
    monkeypatch,
):
    """[대련] 시작 시, 이 답글에 직접 멘션되지 않았어도 스레드의 조상
    게시물에 등장했던 인원은 참여 대상에 포함돼야 한다 — 마스토돈
    클라이언트가 답글 작성 시 이전 멘션을 지우거나 일부만 남겨도 실제
    참여자 전원을 놓치지 않기 위함이다."""
    state = _make_state()
    char_dict = {
        "swordsman_acct": get_test_preset("검사"),
        "archer_acct": get_test_preset("궁수"),
    }
    name_dict = {"검사": get_test_preset("검사"), "궁수": get_test_preset("궁수")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, name_dict, {}),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            char_dict,
            name_dict,
            {},
        ),
    )
    ancestors = [
        {"account": {"acct": "archer_acct"}, "mentions": []},
    ]
    mastodon = _FakeMastodon(ancestors=ancestors)
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    # archer_acct를 명시적으로 멘션하지 않고 [대련]만 보낸다 — 스레드
    # 조상(위 ancestors)에 archer_acct가 등장했으므로 그래도 포함돼야 한다.
    listener.on_notification(_make_notification("swordsman_acct", 1, 500, "[대련]"))

    assert set(_only_practice(state).expected_accts) == {
        "swordsman_acct",
        "archer_acct",
    }


def test_practice_can_be_started_directly_by_character_account(monkeypatch):
    """대련은 상시전투와 달리 Admin 명령어가 아니라 캐릭터 전용 명령어다 —
    등록된 캐릭터 계정이 직접 [대련] @상대를 멘션하면, 발신자 본인과 함께
    멘션된 상대가 참여 대상으로 등록되어야 한다(발신자 스스로를 다시
    멘션할 필요 없음)."""
    state = _make_state()
    char_dict = {
        "swordsman_acct": get_test_preset("검사"),
        "archer_acct": get_test_preset("궁수"),
    }
    name_dict = {"검사": get_test_preset("검사"), "궁수": get_test_preset("궁수")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, name_dict, {}),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            char_dict,
            name_dict,
            {},
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "swordsman_acct", 1, 0, "[대련]", extra_mentions=["archer_acct"]
        )
    )

    assert state.practices
    assert set(_only_practice(state).expected_accts) == {
        "swordsman_acct",
        "archer_acct",
    }
    prep_call = mastodon.status_post_calls[-1]
    assert "@swordsman_acct" in prep_call["status"]
    assert "@archer_acct" in prep_call["status"]


def test_two_practice_sessions_run_concurrently_without_blocking_or_state_bleed(
    monkeypatch,
):
    """대련이 이미 하나 진행 중이어도, 다른 참가자들끼리 시작하는 새 대련이
    막히면 안 된다 — 본 전투(state.session)는 동시에 하나만 가능하지만
    대련/상시전투는 DM 전투처럼 여러 세션이 동시에 진행될 수 있어야 한다.
    두 세션이 서로의 진행(field_id/active_post_id/캐릭터 배치)에 영향을
    주지 않는지도 함께 확인한다."""
    state = _make_state()
    char_dict = {
        "swordsman_acct": get_test_preset("검사"),
        "archer_acct": get_test_preset("궁수"),
        "mage_acct": get_test_preset("마법사"),
        "healer_acct": get_test_preset("힐러"),
    }
    name_dict = {
        "검사": get_test_preset("검사"),
        "궁수": get_test_preset("궁수"),
        "마법사": get_test_preset("마법사"),
        "힐러": get_test_preset("힐러"),
    }
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, name_dict, {}),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            char_dict,
            name_dict,
            {},
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    # 검사/궁수의 대련을 시작한다.
    listener.on_notification(
        _make_notification(
            "swordsman_acct", 1, 0, "[대련]", extra_mentions=["archer_acct"]
        )
    )
    assert len(state.practices) == 1

    # 아직 검사/궁수 대련이 포지션 선언 대기 중인데도, 마법사/힐러가 별도
    # 대련을 시작할 수 있어야 한다 — 예전에는 "이미 진행 중인 대련/상시전투가
    # 있습니다" 오류로 막혔다.
    listener.on_notification(
        _make_notification("mage_acct", 2, 0, "[대련]", extra_mentions=["healer_acct"])
    )
    assert len(state.practices) == 2
    second_prep_reply = mastodon.status_post_calls[-1]
    assert "이미 진행 중인" not in second_prep_reply["status"]

    prep_ids = sorted(state.practices)
    prep_id_1, prep_id_2 = prep_ids

    # 각 세션의 포지션 선언을 완료해 둘 다 활성 페이즈로 전환한다.
    listener.on_notification(
        _make_notification("swordsman_acct", 3, prep_id_1, "[1팀/3열]")
    )
    listener.on_notification(
        _make_notification("archer_acct", 4, prep_id_1, "[2팀/5열]")
    )
    listener.on_notification(_make_notification("mage_acct", 5, prep_id_2, "[1팀/3열]"))
    listener.on_notification(
        _make_notification("healer_acct", 6, prep_id_2, "[2팀/5열]")
    )

    assert len(state.practices) == 2
    sessions = list(state.practices.values())
    field_ids = {ps.field_id for ps in sessions}
    active_post_ids = {ps.active_post_id for ps in sessions}
    assert len(field_ids) == 2  # 서로 다른 field_id로 독립 기록된다
    assert len(active_post_ids) == 2  # 서로 다른 게시물 스레드로 진행된다

    swordsman_ps = next(
        ps for ps in sessions if CharacterId("검사") in ps.context.characters
    )
    mage_ps = next(
        ps for ps in sessions if CharacterId("마법사") in ps.context.characters
    )
    assert swordsman_ps is not mage_ps
    # 서로의 캐릭터가 상대 세션 필드에 새지 않았어야 한다.
    assert CharacterId("마법사") not in swordsman_ps.context.characters
    assert CharacterId("검사") not in mage_ps.context.characters


def test_admin_can_no_longer_start_practice_directly(monkeypatch):
    """대련은 캐릭터 전용 명령어로 바뀌었으므로, Admin 계정이 [대련]을
    보내도 더 이상 대련 세션이 시작되면 안 된다."""
    state = _make_state()
    char_dict = {
        "swordsman_acct": get_test_preset("검사"),
        "archer_acct": get_test_preset("궁수"),
    }
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, char_dict, {}),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[대련]",
            extra_mentions=["swordsman_acct", "archer_acct"],
        )
    )

    assert not state.practices
    reply = mastodon.status_post_calls[-1]
    assert "알 수 없는 관리자 커맨드" in reply["status"]


def test_judge_announce_colon_form_is_silently_ignored():
    """ "[판정: 선착 1인, 55분까지]"처럼 콜론을 쓴 안내문은 캐릭터용
    "[판정/스탯]" 커맨드(슬래시)와 형식이 다르므로, admin이 플레이어 안내문에
    이 표기를 쓰며 봇을 실수로 멘션해도 "알 수 없는 관리자 커맨드" 오류
    없이 조용히 무시되어야 한다."""
    state = _make_state()

    result = admin_module.handle_admin_command(
        "어떻게 할까? [판정: 선착 1인, 55분까지] [마법 4/지식 4/인간 4]", state
    )

    assert result.reply_text == ""
    assert result.game_post_text is None


def test_investigation_battle_remains_admin_only(monkeypatch):
    """상시전투는 대련과 달리 여전히 Admin 전용 명령어다 — 등록된 캐릭터가
    직접 [상시전투]를 보내도 아무 처리도 되면 안 된다(대련 경로로 잘못
    새지 않는지 확인)."""
    state = _make_state()
    char_dict = {"swordsman_acct": get_test_preset("검사")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, char_dict, {}),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("swordsman_acct", 1, 0, "[상시전투]"))

    assert not state.practices
    assert mastodon.status_post_calls == []


def test_investigation_menu_reply_extracts_venue_amid_chatter(monkeypatch):
    """상시조사 메뉴 답글에 사담이 대괄호 앞뒤로 붙어도("[광장] 사담",
    "사담 [광장]") 장소 커맨드로 정상 인식돼야 한다 — 예전엔 답글 전체가
    정확히 "[장소명]"이어야만 파싱되어, 사담이 조금이라도 섞이면 엉뚱한
    문자열로 깨졌다."""
    state = _make_state()
    state.noncombat.investigations["user1"] = InvestigationSession(
        field_id="100", acct="user1", menu_post_id=100
    )
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(
        main_module.noncombat_commands,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [_quest(venue="광장", name="광장 의뢰")],
        ),
    )
    monkeypatch.setattr(
        main_module.noncombat_commands,
        "upsert_investigation_session",
        lambda *a, **k: None,
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("user1", 1, 100, "사담 [광장] 사담"))

    assert "[광장](으)로 이동했다." in mastodon.status_post_calls[-1]["status"]


def test_investigation_venue_choice_resolves_via_thread_ancestors(monkeypatch):
    """메뉴 게시물에 대한 직속 답글이 아니라, 사담을 몇 번 주고받은 뒤의
    중첩된 답글이어도 장소 커맨드가 있으면 스레드 조상을 거슬러 올라가
    같은 세션을 찾아 정상 처리해야 한다."""
    state = _make_state()
    state.noncombat.investigations["user1"] = InvestigationSession(
        field_id="100", acct="user1", menu_post_id=100
    )
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(
        main_module.noncombat_commands,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [_quest(venue="광장", name="광장 의뢰")],
        ),
    )
    monkeypatch.setattr(
        main_module.noncombat_commands,
        "upsert_investigation_session",
        lambda *a, **k: None,
    )
    # 메뉴(100) → 사담(101) → 사담(102) 순으로 스레드가 이어졌고, 이번
    # 답글은 102에 대한 답글이다 — 메뉴 게시물(100)의 직속 답글이 아니다.
    ancestors = [
        {"id": 100, "account": {"acct": "bot"}, "mentions": []},
        {"id": 101, "account": {"acct": "user1"}, "mentions": []},
        {"id": 102, "account": {"acct": "user2"}, "mentions": []},
    ]
    mastodon = _FakeMastodon(ancestors=ancestors)
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("user1", 1, 102, "[광장]"))

    assert "[광장](으)로 이동했다." in mastodon.status_post_calls[-1]["status"]


def test_investigation_bare_chat_reply_does_nothing_and_keeps_session_open(
    monkeypatch,
):
    """메뉴 게시물에 장소 커맨드도 [자율 탐사]도 없는 순수 사담 답글은
    (직속 답글이라도) 아무 응답도 남기지 않고 세션도 끝나지 않아야 한다 —
    [자율 탐사]를 명시적으로 입력해야만 world로 인계된다."""
    state = _make_state()
    state.noncombat.investigations["user1"] = InvestigationSession(
        field_id="100", acct="user1", menu_post_id=100
    )
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("user1", 1, 100, "그냥 둘러본다"))

    assert mastodon.status_post_calls == []
    assert state.noncombat.investigations["user1"].ended is False


def test_investigation_explicit_free_explore_ends_session_and_stops_matching(
    monkeypatch,
):
    """[자율 탐사]를 명시적으로 입력하면 world가 태그되며 세션이 종료되고,
    그 뒤로는 같은 메뉴 게시물에 실제 장소 커맨드를 보내도 더 이상
    처리되지 않아야 한다."""
    state = _make_state()
    state.noncombat.investigations["user1"] = InvestigationSession(
        field_id="100", acct="user1", menu_post_id=100
    )
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(
        main_module.noncombat_commands,
        "upsert_investigation_session",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        main_module.noncombat_commands,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest(venue="광장")]),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("user1", 1, 100, "[자율 탐사]"))

    assert "다른 곳에 가보기로 했다" in mastodon.status_post_calls[-1]["status"]
    assert state.noncombat.investigations["user1"].ended is True

    calls_before = len(mastodon.status_post_calls)

    listener.on_notification(_make_notification("user1", 2, 100, "[광장]"))

    assert len(mastodon.status_post_calls) == calls_before


def test_investigation_nested_casual_chat_does_not_end_session(monkeypatch):
    """스레드 조상으로만 세션과 연결되는(직속 답글이 아닌) 사담은 세션을
    끝내지 않고 아무 응답도 남기지 않아야 한다 — 뒤이어 실제 장소 커맨드가
    올 수 있으므로."""
    state = _make_state()
    state.noncombat.investigations["user1"] = InvestigationSession(
        field_id="100", acct="user1", menu_post_id=100
    )
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    ancestors = [{"id": 100, "account": {"acct": "bot"}, "mentions": []}]
    mastodon = _FakeMastodon(ancestors=ancestors)
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("user1", 1, 555, "그냥 사담이다"))

    assert mastodon.status_post_calls == []
    assert state.noncombat.investigations["user1"].ended is False


def test_world_account_can_start_investigation_battle(monkeypatch):
    """world 계정(WORLD_MASTODON_ID)은 [상시전투] 개시(+ 같은 메시지의
    적군 배치)를 admin과 동등하게 사용할 수 있어야 한다."""
    state = _make_state()
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터")
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "test-world",
            1,
            0,
            "[상시전투] [배치/적 캐릭터/적군 1열]",
            extra_mentions=["moirak_test"],
        )
    )

    assert len(state.practices) == 1
    ps = _only_practice(state)
    assert ps.is_investigation
    assert ps.expected_accts == ["moirak_test"]
    assert "상시전투 준비" in mastodon.status_post_calls[-1]["status"]


def test_world_account_cannot_use_other_admin_commands(monkeypatch):
    """world 계정은 [상시전투] 개시/프록시 이외의 admin 전용 커맨드([전투준비]
    등)에는 접근할 수 없어야 한다."""
    state = _make_state()
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-world", 1, 0, "[전투준비]"))

    assert state.session is not None and not state.session.started
    assert mastodon.status_post_calls == []


def _start_active_investigation(
    state: BotState,
    *,
    ally_acct: str = "ally_test",
    active_post_id: int = 5000,
    enemy_max_hp: int = 500,
) -> PracticeBattleState:
    """이미 개시되어 특정 페이즈에 놓인 상시전투를 직접 조립한다 — 아군
    1명(계정 있음, SIDE_1)과 에너미 1명(계정 없음, SIDE_2)이 배치돼 있다.
    호출측이 set_phase_for_restore로 원하는 페이즈/선공·후공을 지정한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("아군"), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적", max_hp=enemy_max_hp),
        SideType.SIDE_2,
        BattlefieldColumnIndex(0),
    )
    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(
        context=ctx,
        manager=manager,
        is_investigation=True,
        expected_accts=[ally_acct],
        active_post_id=active_post_id,
        round_limit=5,
    )
    state.practices[active_post_id] = ps
    state.char_dict[ally_acct] = get_test_preset("아군")
    return ps


def test_admin_proxy_for_investigation_enemy_advances_to_next_round(monkeypatch):
    """계정이 없는 에너미가 그 라운드의 마지막 행동(후공)을 admin 프록시로
    수행하면, 캐릭터 본인 답글과 동일하게 자동으로 다음 라운드(선공
    페이즈)로 전환돼야 한다 — 예전에는 프록시 경로가 이 전환을 전혀 하지
    않아, 에너미가 후공으로 행동한 순간 상시전투가 영구히 멈췄다."""
    state = _make_state()
    ps = _start_active_investigation(state)
    ps.round_n = 1
    ps.first_mover = SideType.SIDE_1
    ps.second_mover = SideType.SIDE_2
    ps.manager.set_phase_for_restore(
        PracticeRoundPhase.SECOND_MOVER_ACTION, SideType.SIDE_1, SideType.SIDE_2
    )
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification("test-admin", 1, ps.active_post_id, "◊ 적 [공격/아군]")
    )

    assert ps.round_n == 2
    assert ps.phase == PracticeRoundPhase.FIRST_MOVER_ACTION
    game_post = mastodon.status_post_calls[-1]["status"]
    assert "[2라운드] 선공" in game_post
    # 다음 라운드 안내 게시물이 새 active_post_id로 등록돼 있어야 이어서
    # 커맨드를 받을 수 있다.
    assert ps.active_post_id in state.practices


def test_world_proxy_for_investigation_enemy_also_advances_round(monkeypatch):
    """world 계정의 상시전투 프록시도 admin과 동일하게 자동 전환돼야
    한다."""
    state = _make_state()
    ps = _start_active_investigation(state)
    ps.round_n = 1
    ps.first_mover = SideType.SIDE_1
    ps.second_mover = SideType.SIDE_2
    ps.manager.set_phase_for_restore(
        PracticeRoundPhase.SECOND_MOVER_ACTION, SideType.SIDE_1, SideType.SIDE_2
    )
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification("test-world", 1, ps.active_post_id, "◊ 적 [공격/아군]")
    )

    assert ps.round_n == 2
    assert ps.phase == PracticeRoundPhase.FIRST_MOVER_ACTION


def test_world_proxy_cannot_control_duel_participants(monkeypatch):
    """world 계정의 프록시 권한은 상시전투 참가자로 한정된다 — 대련
    (is_investigation=False)은 참가자 전원이 실제 계정이라 world가 대신
    조작할 수 없어야 한다."""
    state = _make_state()
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("검사"), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("궁수"), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )
    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(
        context=ctx,
        manager=manager,
        is_investigation=False,
        expected_accts=["swordsman_acct", "archer_acct"],
        active_post_id=6000,
    )
    ps.round_n = 1
    ps.manager.set_phase_for_restore(
        PracticeRoundPhase.FIRST_MOVER_ACTION, SideType.SIDE_1, SideType.SIDE_2
    )
    state.practices[6000] = ps
    archer_hp_before = ps.context.characters[CharacterId("궁수")].status.curr_hp
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification("test-world", 1, 6000, "◊ 검사 [공격/궁수]")
    )

    # world는 대련 참가자가 아니므로 프록시로 대신 행동시킬 수 없다 — 라운드/
    # 페이즈가 그대로고, 궁수도 대미지를 입지 않아야 한다. (in_reply_to_id가
    # 활성 대련 게시물과 일치해 "등록된 캐릭터를 찾을 수 없습니다" 같은 에러
    # 답글 자체는 갈 수 있지만, 실제 공격은 전혀 적용되지 않는다.)
    assert ps.round_n == 1
    assert ps.phase == PracticeRoundPhase.FIRST_MOVER_ACTION
    archer_hp_after = ps.context.characters[CharacterId("궁수")].status.curr_hp
    assert archer_hp_after == archer_hp_before


def test_practice_ends_immediately_when_round_end_dot_wipes_a_side():
    """대련은 이미 공격으로 한쪽이 즉시 전멸하면 그 자리에서 승자를 선언하고
    종료된다. 이 테스트는 그중 놓치기 쉬운 경로 하나를 확인한다 — 후공 차례
    처리 중 ps.end_round()가 적용하는 라운드 종료 DoT로 전멸이 일어나는
    경우도, 다음 라운드까지 기다리지 않고 그 즉시 종료되어야 한다(HP는
    end_round() 이후에 다시 계산해야 한다)."""
    dot_buff = BuffData(
        id="맹독",
        buff_class_name="BuffDamageOverTime",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=999,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="",
    )
    ctx = PracticeBattlefieldContext(buff_dict={"맹독": dot_buff}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    ctx.buff_container.add(
        BuffAddData(
            given_by=CharacterId("A"), applied_to=CharacterId("B"), buff_id="맹독"
        )
    )

    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(context=ctx, manager=manager, round_limit=5)
    ps.start_round()

    side_to_acct = {SideType.SIDE_1: "acct_a", SideType.SIDE_2: "acct_b"}
    state = BotState(
        char_dict={
            "acct_a": get_test_preset("A"),
            "acct_b": get_test_preset("B"),
        },
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    ps.active_post_id = 5000
    state.practices[5000] = ps

    first_acct = side_to_acct[ps.first_mover]
    _, _, game_post, _, _ = _handle_practice_command(first_acct, "[이동/2]", state, ps)
    assert "종료" not in game_post  # 아직 전멸 전 — 라운드가 계속돼야 한다

    second_acct = side_to_acct[ps.second_mover]
    _, _, game_post, _, _ = _handle_practice_command(second_acct, "[이동/2]", state, ps)

    assert "종료" in game_post
    assert "승자: 1팀" in game_post
    assert not state.practices


def test_practice_end_summary_hides_buffs_and_shows_winner_roster():
    """대련 종료 게시물에는 남아 있는 버프/디버프 요약이 나오면 안 되고,
    "승자: N팀" 뒤에 그 팀의 생존 캐릭터 명단이 "(이름, 이름)" 형식으로
    붙어야 한다."""
    dot_buff = BuffData(
        id="맹독",
        buff_class_name="BuffDamageOverTime",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=999,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="",
    )
    atk_buff = BuffData(
        id="공격력 증가",
        buff_class_name="BuffAtk",
        duration_turn_value=5,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=3,
        condition_=None,
        condition_value=None,
        is_debuff=False,
        description="",
    )
    ctx = PracticeBattlefieldContext(
        buff_dict={"맹독": dot_buff, "공격력 증가": atk_buff}, skill_dict={}
    )
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("C"), SideType.SIDE_1, BattlefieldColumnIndex(1))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    ctx.buff_container.add(
        BuffAddData(
            given_by=CharacterId("A"), applied_to=CharacterId("B"), buff_id="맹독"
        )
    )
    # 승자 측(A)에 살아남는 버프를 걸어, 종료 요약에서 실제로 숨겨지는지 확인.
    ctx.buff_container.add(
        BuffAddData(
            given_by=CharacterId("A"),
            applied_to=CharacterId("A"),
            buff_id="공격력 증가",
        )
    )

    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(context=ctx, manager=manager, round_limit=5)
    ps.start_round()

    side_to_acct = {SideType.SIDE_1: "acct_a", SideType.SIDE_2: "acct_b"}
    state = BotState(
        char_dict={
            "acct_a": get_test_preset("A"),
            "acct_c": get_test_preset("C"),
            "acct_b": get_test_preset("B"),
        },
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    ps.active_post_id = 5000
    state.practices[5000] = ps

    first_acct = side_to_acct[ps.first_mover]
    _, _, game_post, _, _ = _handle_practice_command(first_acct, "[이동/2]", state, ps)
    assert "종료" not in game_post  # 아직 전멸 전 — 라운드가 계속돼야 한다

    second_acct = side_to_acct[ps.second_mover]
    _, _, game_post, _, _ = _handle_practice_command(second_acct, "[이동/2]", state, ps)

    assert "종료" in game_post
    assert "승자: 1팀 (A, C)" in game_post
    # HP 보드는 여전히 나와야 한다.
    assert "1팀" in game_post and "2팀" in game_post
    # 버프/디버프 요약(대괄호 라벨 + 설명줄)은 나오면 안 된다.
    assert "[공격력 증가]" not in game_post
    assert "↳" not in game_post
    assert not state.practices


def test_practice_battle_end_applies_hooks_before_computing_winner_and_shows_calc():
    """전투 종료 시점 버프 훅([재앙] 등, BuffBase.on_battle_end())이 대련에서도
    승자 계산 전에 반영돼야 하고, 그 결과(계산식 포함)가 종료 메시지에
    나와야 한다."""
    curse_buff = BuffData(
        id="재앙",
        buff_class_name="BuffCatastrophe",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=None,
        value=0,
        condition_=None,
        condition_value=None,
        is_debuff=False,
        description="",
        max_stack=20,
    )
    ctx = PracticeBattlefieldContext(buff_dict={"재앙": curse_buff}, skill_dict={})
    # PracticeBattlefieldContext.add_character()는 curr_hp를 항상
    # max_hp // 2로 초기화하므로(initial_hp는 무시됨), A/B 모두 시작
    # 시점엔 정확히 50%로 동률이다.
    ctx.add_character(
        get_test_preset("A", max_hp=100), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("B", max_hp=100), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )
    # 재앙 5스택 × 3 = 15 감소. A만 이 훅으로 50 → 35(35%)까지 깎여
    # B(50%)보다 열세가 되므로, 승자 계산이 반드시 이 훅 이후에 일어나야
    # B(2팀)가 승리로 나온다.
    ctx.buff_container.add(
        BuffAddData(
            given_by=CharacterId("A"),
            applied_to=CharacterId("A"),
            buff_id="재앙",
            stack_value=5,
        )
    )

    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(context=ctx, manager=manager, round_limit=1)
    ps.start_round()

    side_to_acct = {SideType.SIDE_1: "acct_a", SideType.SIDE_2: "acct_b"}
    state = BotState(
        char_dict={
            "acct_a": get_test_preset("A"),
            "acct_b": get_test_preset("B"),
        },
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    ps.active_post_id = 5000
    state.practices[5000] = ps

    first_acct = side_to_acct[ps.first_mover]
    _handle_practice_command(first_acct, "[이동/2]", state, ps)
    second_acct = side_to_acct[ps.second_mover]
    _, _, game_post, _, _ = _handle_practice_command(second_acct, "[이동/2]", state, ps)

    assert "종료" in game_post
    assert ctx.characters[CharacterId("A")].status.curr_hp == 35
    assert "승자: 2팀 (B)" in game_post
    assert "**【전투 종료 처리】**" in game_post
    assert "→" in game_post
    assert not state.practices


def test_practice_field_text_uses_team_labels_not_faction_labels():
    """대련은 아군/적군 구도가 아니므로, 필드 상황 텍스트도 팀 커맨드([1팀/...])와
    맞춰 "1팀"/"2팀" 헤더를 써야 한다 — 본 전투용 "아군"/"적군" 표현이 새어
    나오면 안 된다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    ps = PracticeBattleState(
        context=ctx, manager=PracticeRoundManager(ctx), is_investigation=False
    )

    text = main_module._field_text(ps)

    assert "1팀\n" in text
    assert "2팀\n" in text
    assert "아군" not in text
    assert "적군" not in text


def test_investigation_field_text_still_uses_faction_labels():
    """상시전투는 대련과 같은 SIDE_1/SIDE_2 메커니즘을 쓰지만, 안내 문구
    (side_label)가 이미 "아군"/"적군"을 쓰므로 필드 텍스트도 그대로 유지돼야
    한다 — 대련 대응이 상시전투까지 "1팀"/"2팀"으로 바꿔버리면 안 된다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    ps = PracticeBattleState(
        context=ctx, manager=PracticeRoundManager(ctx), is_investigation=True
    )

    text = main_module._field_text(ps)

    assert "아군\n" in text
    assert "적군\n" in text
    assert "1팀" not in text
    assert "2팀" not in text


def test_practice_field_text_shows_team_1_before_team_2():
    """대련 필드 텍스트에서 "2팀"이 항상 먼저 출력되면 팀 번호 순서와
    어긋나 헷갈린다 — "1팀"이 먼저, "2팀"이 나중에 출력돼야 한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    ps = PracticeBattleState(
        context=ctx, manager=PracticeRoundManager(ctx), is_investigation=False
    )

    text = main_module._field_text(ps)

    assert text.index("1팀\n") < text.index("2팀\n")


def test_investigation_field_text_still_shows_enemy_before_ally():
    """상시전투는 본 전투 필드 이미지와 같은 순서(적군 먼저, 아군 나중)를
    유지해야 한다 — 대련의 "1팀 먼저" 대응이 상시전투까지 건드리면 안
    된다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    ps = PracticeBattleState(
        context=ctx, manager=PracticeRoundManager(ctx), is_investigation=True
    )

    text = main_module._field_text(ps)

    assert text.index("적군\n") < text.index("아군\n")


def test_practice_field_text_hides_empty_columns():
    """대련/상시전투 필드 텍스트는 게시물 길이 제한(500자) 안에 버프 요약도
    함께 넣어야 하므로, 캐릭터가 배치되지 않은 열은 아예 줄을 그리지 않아야
    한다 — 7열 전부를 항상 그리면 대부분 빈 칸("-")뿐인데도 길이가 금방
    한도를 넘긴다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    ps = PracticeBattleState(
        context=ctx, manager=PracticeRoundManager(ctx), is_investigation=False
    )

    text = main_module._field_text(ps)

    assert "[1]" in text
    assert "[2]" not in text
    assert "[7]" not in text


def test_practice_retire_command_removes_character_and_continues_when_teammate_remains():
    """[탈락]은 선공/후공 순서와 무관하게 즉시 처리되며, 같은 편에 남은
    캐릭터가 있으면 전투가 계속돼야 한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("A2"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(context=ctx, manager=manager, round_limit=5)
    ps.start_round()

    state = BotState(
        char_dict={
            "acct_a": get_test_preset("A"),
            "acct_a2": get_test_preset("A2"),
            "acct_b": get_test_preset("B"),
        },
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    ps.active_post_id = 5000
    state.practices[5000] = ps

    reply, _calc, game_post, _log, _ended = _handle_practice_command(
        "acct_a", "[탈락]", state, ps
    )

    assert "탈락" in reply
    assert CharacterId("A") not in ctx.characters
    assert game_post is None  # 종료 게시물 없음 — 같은 편에 A2가 남아 있다
    assert state.practices


def test_practice_retire_command_ends_battle_when_side_wiped():
    """1v1에서 [탈락]으로 한쪽이 전멸하면 그 즉시 상대 팀 승리로 대련이
    종료돼야 한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(context=ctx, manager=manager, round_limit=5)
    ps.start_round()

    state = BotState(
        char_dict={
            "acct_a": get_test_preset("A"),
            "acct_b": get_test_preset("B"),
        },
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    ps.active_post_id = 5000
    state.practices[5000] = ps

    reply, _calc, game_post, _log, _ended = _handle_practice_command(
        "acct_a", "[탈락]", state, ps
    )

    assert "탈락" in reply
    assert game_post is not None
    assert "종료" in game_post
    assert "승자: 2팀" in game_post
    assert not state.practices


def test_practice_winner_uses_hp_ratio_not_absolute_total():
    """팀 인원/최대 체력 총량이 다르면 절대 체력 합 비교는 불공평하다 —
    예를 들어 1팀(50/100=50%)이 2팀(60/200=30%)보다 체력 비율은 높지만
    절대 합은 더 낮은 경우, 승자는 비율이 더 높은 1팀이어야 한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("A", max_hp=100), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("B", max_hp=200), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )
    ps = PracticeBattleState(context=ctx, manager=PracticeRoundManager(ctx))

    char_a = ctx.characters[CharacterId("A")]
    char_b = ctx.characters[CharacterId("B")]
    # add_character가 대련이라 max_hp를 절반으로 만들므로(100→50, 200→100),
    # 그 절반 기준으로 curr_hp를 다시 맞춘다: A는 50%(25/50), B는 30%(30/100).
    char_a.status.curr_hp = 25
    char_b.status.curr_hp = 30

    assert ps.winner() == SideType.SIDE_1


def test_practice_winner_breaks_ratio_tie_with_absolute_hp():
    """체력 비율이 동률이면 절대 체력 합이 더 높은 쪽이 승자다 — 예를 들어
    1팀(25/50=50%)과 2팀(50/100=50%)처럼 비율이 같더라도, 절대 체력이 더
    많은 2팀이 이겨야 한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("A", max_hp=100), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("B", max_hp=200), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )
    ps = PracticeBattleState(context=ctx, manager=PracticeRoundManager(ctx))

    char_a = ctx.characters[CharacterId("A")]
    char_b = ctx.characters[CharacterId("B")]
    # add_character가 대련이라 max_hp를 절반으로 만드므로(100→50, 200→100).
    # 두 팀 다 비율 50%지만 절대 체력은 2팀(50)이 1팀(25)보다 높다.
    char_a.status.curr_hp = 25
    char_b.status.curr_hp = 50

    assert ps.winner() == SideType.SIDE_2


def test_practice_winner_is_draw_when_ratio_and_absolute_hp_both_tie():
    """체력 비율뿐 아니라 절대 체력 합까지 같으면 무승부(None)여야 한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("A", max_hp=100), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("B", max_hp=100), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )
    ps = PracticeBattleState(context=ctx, manager=PracticeRoundManager(ctx))

    char_a = ctx.characters[CharacterId("A")]
    char_b = ctx.characters[CharacterId("B")]
    char_a.status.curr_hp = 25
    char_b.status.curr_hp = 25

    assert ps.winner() is None


def test_practice_command_with_two_bracket_groups_is_rejected_with_explicit_error():
    """캐릭터 계정이 대괄호를 두 개로 나눠 보내면(예: '[A] [B]'), 파서의 탐욕적
    매칭 때문에 하나만 조용히 처리되고 나머지가 사라지는 문제가 있었다 —
    대련/상시전투 경로에서도 사전에 걸러 명시적 에러를 내야 한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(context=ctx, manager=manager, round_limit=5)
    ps.start_round()

    state = BotState(
        char_dict={"acct_a": get_test_preset("A")},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    ps.active_post_id = 5000
    state.practices[5000] = ps

    reply, _calc_text, game_post, battle_log, _ended = _handle_practice_command(
        "acct_a", "[이동/2] [이동/3]", state, ps
    )

    assert "대괄호 커맨드를 하나만" in reply
    assert game_post is None
    assert battle_log is None


def test_practice_declaration_out_of_range_column_gets_error_reply_and_can_retry(
    monkeypatch,
):
    """[N팀/9열]처럼 열 번호가 범위를 벗어나면 예전에는 완전히 무응답이었다 —
    이제는 본 전투와 동일하게 validation error를 답글로 보내고, 이후
    올바른 형식으로 다시 보내면 정상적으로 선언이 성립해야 한다."""
    state = _make_state()
    char_dict = {
        "swordsman_acct": get_test_preset("검사"),
        "archer_acct": get_test_preset("궁수"),
    }
    name_dict = {"검사": get_test_preset("검사"), "궁수": get_test_preset("궁수")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, name_dict, {}),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            char_dict,
            name_dict,
            {},
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "swordsman_acct",
            1,
            0,
            "[대련]",
            visibility="unlisted",
            extra_mentions=["archer_acct"],
        )
    )
    prep_post_id = _only_practice(state).prep_post_id

    listener.on_notification(
        _make_notification("swordsman_acct", 2, prep_post_id, "[1팀/9열]")
    )

    error_reply = mastodon.status_post_calls[-1]
    assert "인식할 수 없습니다" in error_reply["status"]
    assert "swordsman_acct" not in _only_practice(state).declared

    # 형식을 고쳐 재시도하면 정상적으로 선언이 성립해야 한다.
    listener.on_notification(
        _make_notification("swordsman_acct", 3, prep_post_id, "[1팀/3열]")
    )
    assert "swordsman_acct" in _only_practice(state).declared


def test_practice_idle_chat_reply_is_silently_ignored(monkeypatch):
    """대련/상시전투는 스레드 하나가 계속 이어지는 구조라, 참가자가 대괄호
    커맨드 없이 잡담(사담)만 답글로 달아도 에러 답글로 스레드를 어지럽히면
    안 된다 — 커맨드가 올 때까지 조용히 무시하고, active_post_id도 그대로
    유지해 이후 정상 커맨드가 문제없이 이어지게 해야 한다."""
    state = _make_state()
    char_dict = {
        "swordsman_acct": get_test_preset("검사"),
        "archer_acct": get_test_preset("궁수"),
    }
    name_dict = {"검사": get_test_preset("검사"), "궁수": get_test_preset("궁수")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, name_dict, {}),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            char_dict,
            name_dict,
            {},
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "swordsman_acct",
            1,
            0,
            "[대련]",
            visibility="unlisted",
            extra_mentions=["archer_acct"],
        )
    )
    prep_post_id = _only_practice(state).prep_post_id
    listener.on_notification(
        _make_notification("swordsman_acct", 2, prep_post_id, "[1팀/1열]")
    )
    listener.on_notification(
        _make_notification("archer_acct", 3, prep_post_id, "[2팀/1열]")
    )
    active_post_id = _only_practice(state).active_post_id
    calls_before = len(mastodon.status_post_calls)

    listener.on_notification(
        _make_notification("swordsman_acct", 4, active_post_id, "화이팅!")
    )

    assert len(mastodon.status_post_calls) == calls_before  # 새 게시물이 없어야 한다
    assert (
        _only_practice(state).active_post_id == active_post_id
    )  # 타래가 그대로 유지된다

    # 이어서 정상 커맨드를 보내면 여전히 같은 게시물에 답글로 이어져야 한다.
    listener.on_notification(
        _make_notification("swordsman_acct", 5, active_post_id, "[이동/2]")
    )
    assert len(mastodon.status_post_calls) > calls_before


def _setup_dm_battle_state(monkeypatch, enemy_max_hp: int = 100):
    """DM 전투 테스트 공용 셋업. (mastodon, listener, state, char_dict, name_dict) 반환.

    "전사"는 아군 랜덤 배치로 어느 열에 놓이든 "고블린"을 공격할 수 있어야
    하므로 attack_range를 전체 열 폭(7)으로 넉넉히 잡는다 — 그렇지 않으면
    무작위 배치 결과에 따라 사거리 밖 판정으로 테스트가 간헐적으로 실패한다.
    """
    monkeypatch.setattr(
        log_sheets, "_load_hp_write_targets", lambda spreadsheet, cache=None: {}
    )
    state = _make_state()
    char_dict = {"player_acct": get_test_preset("전사", attack_range=7)}
    name_dict = {
        "전사": get_test_preset("전사", attack_range=7),
        "고블린": get_test_preset("고블린", max_hp=enemy_max_hp),
    }
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, name_dict, {}),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            char_dict,
            name_dict,
            {},
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")
    return mastodon, listener, state, char_dict, name_dict


def test_dm_battle_idle_chat_reply_is_silently_ignored(monkeypatch):
    """DM 전투도 대련/상시전투와 동일하게 스레드 하나가 계속 이어지는
    구조다 — 참가자가 대괄호 커맨드 없이 잡담만 답글로 달아도 에러 답글
    없이 조용히 무시하고, active_post_id도 그대로 유지해야 한다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )
    dm_state = next(iter(state.dm_battles.values()))
    pre_post_id = dm_state.active_post_id
    listener.on_notification(_make_notification("test-admin", 2, pre_post_id, "[진행]"))
    active_post_id = dm_state.active_post_id
    calls_before = len(mastodon.status_post_calls)

    listener.on_notification(
        _make_notification("player_acct", 3, active_post_id, "다들 화이팅!")
    )

    assert len(mastodon.status_post_calls) == calls_before
    assert dm_state.active_post_id == active_post_id

    # 이어서 정상 커맨드를 보내면 여전히 같은 게시물에 답글로 이어져야 한다.
    listener.on_notification(
        _make_notification("player_acct", 4, active_post_id, "[공격/고블린]")
    )
    assert len(mastodon.status_post_calls) > calls_before


def test_dm_battle_start_places_enemy_by_command_and_allies_by_mention(monkeypatch):
    """[전투 발생][배치/이름/열]은 적만 그 위치에 배치하고, admin이 함께
    멘션한 계정 중 char_dict에 등록된 캐릭터는 참전 신청 없이 자동으로
    아군 무작위 배치되어야 한다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )

    assert len(state.dm_battles) == 1
    dm_state = next(iter(state.dm_battles.values()))
    goblin_id = CharacterId("고블린")
    warrior_id = CharacterId("전사")
    assert goblin_id in dm_state.session.context.characters
    assert warrior_id in dm_state.session.context.characters
    assert dm_state.session.context.characters[goblin_id].faction == FactionType.ENEMY
    assert dm_state.session.context.characters[warrior_id].faction == FactionType.ALLY
    assert dm_state.session.context.find_character_position(
        goblin_id
    ) == BattlefieldColumnIndex.from_str("1열")
    assert dm_state.session.started is True


def test_dm_battle_game_posts_mention_participants_so_they_remain_visible(monkeypatch):
    """DM 전투는 visibility="direct"라 그 게시물 자체에 명시적으로 멘션된
    계정만 볼 수 있다 — 전투 시작/페이즈 전환/종료 게시물이 [전투 발생]에
    함께 멘션됐던 참가자를 다시 멘션하지 않으면, 참가자 본인은 자기 턴
    게시물을 서버에서 아예 조회할 수 없어(404) 답글도 달 수 없게 된다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch, enemy_max_hp=1
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )
    start_call = mastodon.status_post_calls[-1]
    assert "@player_acct" in start_call["status"]

    dm_state = next(iter(state.dm_battles.values()))
    pre_post_id = dm_state.active_post_id

    listener.on_notification(_make_notification("test-admin", 2, pre_post_id, "[진행]"))
    ally_call = mastodon.status_post_calls[-1]
    assert "@player_acct" in ally_call["status"]

    active_post_id = dm_state.active_post_id
    listener.on_notification(
        _make_notification("player_acct", 3, active_post_id, "[공격/고블린]")
    )
    end_call = mastodon.status_post_calls[-1]
    assert "전투 종료" in end_call["status"]
    assert "@player_acct" in end_call["status"]


def test_dm_battle_start_silently_accepts_faction_prefixed_column(monkeypatch):
    """DM 전투의 [배치/이름/열]은 진영 지정이 없는 문법이지만(배치 대상이
    항상 적군으로 고정), 본 전투 문법인 [배치/이름/적군 N열]을 실수로 그대로
    써도 에러 없이 "적군" 부분을 무시하고 열만 적용해야 한다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/적군 1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )

    assert len(state.dm_battles) == 1
    dm_state = next(iter(state.dm_battles.values()))
    goblin_id = CharacterId("고블린")
    assert goblin_id in dm_state.session.context.characters
    assert dm_state.session.context.find_character_position(
        goblin_id
    ) == BattlefieldColumnIndex.from_str("1열")


def test_dm_battle_thread_visibility_and_wipe_ends_automatically(monkeypatch):
    """DM 전투의 모든 게시물은 최초 [전투 발생] DM의 visibility를 따르고 서로
    답글로 이어지며, 아군 커맨드로 적이 전멸하면 admin의 [진행] 없이 즉시
    전투가 종료되고 state.dm_battles에서 제거되어야 한다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch, enemy_max_hp=1
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )
    pre_call = mastodon.status_post_calls[-1]
    assert pre_call["visibility"] == "direct"
    assert pre_call["in_reply_to_id"] == 1
    dm_state = next(iter(state.dm_battles.values()))
    pre_post_id = dm_state.active_post_id

    # admin 프록시로 적 PRE 선언 (이동만, 대미지 없음)
    listener.on_notification(
        _make_notification("test-admin", 2, pre_post_id, "고블린 [이동/2열]")
    )
    proxy_reply = mastodon.status_post_calls[-1]
    assert "고블린" in name_dict  # sanity
    assert str(dm_state.session.context) in proxy_reply["status"]

    # admin이 [진행]으로 ALLY_ACTION 진입 — admin에게 보낸 확인 답글 뒤에
    # 이어져야 한다(이전 공지에 다시 답글로 달면 확인 답글과 형제가 되어
    # 스레드가 갈라진다).
    calls_before_advance = len(mastodon.status_post_calls)
    listener.on_notification(_make_notification("test-admin", 3, pre_post_id, "[진행]"))
    confirmation_id = 9000 + calls_before_advance
    ally_call = mastodon.status_post_calls[-1]
    assert ally_call["visibility"] == "direct"
    assert ally_call["in_reply_to_id"] == confirmation_id
    assert ally_call["in_reply_to_id"] != pre_post_id
    active_post_id = dm_state.active_post_id
    assert active_post_id != pre_post_id

    # 아군이 공격해 적을 전멸시킴 — [진행] 없이 즉시 종료돼야 함
    listener.on_notification(
        _make_notification("player_acct", 4, active_post_id, "[공격/고블린]")
    )

    end_call = mastodon.status_post_calls[-1]
    assert end_call["visibility"] == "direct"
    assert end_call["in_reply_to_id"] == active_post_id
    assert "전투 종료" in end_call["status"]
    assert "아군" in end_call["status"]
    assert state.dm_battles == {}


def test_dm_battle_phase_posts_chain_off_confirmation_not_stale_post(monkeypatch):
    """DM 전투의 관리자 주도 페이즈 전환([진행] 정산/라운드 종료, [전투 속행])도
    대련과 같은 패턴으로 스레드가 갈라지지 않아야 한다 — 각 페이즈 공지는
    admin에게 보낸 확인 답글 뒤에 이어져야지, 이전 페이즈 공지에 다시
    답글로 달려 확인 답글과 형제가 되면 안 된다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch, enemy_max_hp=100
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )
    dm_state = next(iter(state.dm_battles.values()))
    tip = dm_state.active_post_id

    def advance(status_id, text):
        nonlocal tip
        calls_before = len(mastodon.status_post_calls)
        listener.on_notification(_make_notification("test-admin", status_id, tip, text))
        confirmation_id = 9000 + calls_before
        game_post_call = mastodon.status_post_calls[-1]
        assert game_post_call["in_reply_to_id"] == confirmation_id
        assert game_post_call["in_reply_to_id"] != tip
        tip = dm_state.active_post_id

    # [진행] → ALLY_ACTION
    advance(2, "[진행]")

    # 아군 커맨드(고블린을 전멸시키지 않을 정도로만 공격) — 별도 game_post 없음
    listener.on_notification(_make_notification("player_acct", 3, tip, "[공격/고블린]"))
    tip = dm_state.active_post_id

    # [진행] → ENEMY_POST_ACTION (정산)
    advance(4, "[진행]")

    # [진행] → 라운드 종료
    advance(5, "[진행]")

    # [전투 속행] → 다음 라운드 시작
    advance(6, "[전투 속행]")


def test_dm_battle_character_reply_always_includes_field_board(monkeypatch):
    """DM 전투는 실시간 확인 수단이 답글뿐이므로, 아군 커맨드 답글에도 매번
    현재 필드 상태(str(context))가 포함되어야 한다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch, enemy_max_hp=100
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )
    dm_state = next(iter(state.dm_battles.values()))
    pre_post_id = dm_state.active_post_id

    listener.on_notification(_make_notification("test-admin", 2, pre_post_id, "[진행]"))
    active_post_id = dm_state.active_post_id

    listener.on_notification(
        _make_notification("player_acct", 3, active_post_id, "[공격/고블린]")
    )

    # 계산식이 있으면 본문(필드 상태가 덧붙은 텍스트)은 spoiler_text로,
    # 계산식은 status(계산식만 담긴 CW 본문)로 들어간다 — 답글로 온 첫
    # 게시물 호출을 확인하고 사용자에게 실제로 보이는 두 필드를 합쳐 확인한다.
    reply_calls = [c for c in mastodon.status_post_calls if "in_reply_to_id" in c]
    char_reply = reply_calls[-1]
    visible_text = char_reply.get("spoiler_text", "") + char_reply["status"]
    assert str(dm_state.session.context) in visible_text


def test_dm_battles_run_concurrently_without_state_bleed(monkeypatch):
    """두 개의 DM 전투가 동시에 진행되어도 서로의 상태(적/아군 배치, 라운드)가
    섞이면 안 된다 — state.dm_battles는 여러 인스턴스를 동시에 관리해야 한다."""
    monkeypatch.setattr(
        log_sheets, "_load_hp_write_targets", lambda spreadsheet, cache=None: {}
    )
    state = _make_state()
    char_dict = {
        "player1_acct": get_test_preset("전사1"),
        "player2_acct": get_test_preset("전사2"),
    }
    name_dict = {
        "전사1": get_test_preset("전사1"),
        "전사2": get_test_preset("전사2"),
        "고블린": get_test_preset("고블린"),
        "오크": get_test_preset("오크"),
    }
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (char_dict, name_dict, {}),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            char_dict,
            name_dict,
            {},
        ),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player1_acct"],
        )
    )
    listener.on_notification(
        _make_notification(
            "test-admin",
            2,
            0,
            "[전투 발생][배치/오크/2열]",
            visibility="direct",
            extra_mentions=["player2_acct"],
        )
    )

    assert len(state.dm_battles) == 2
    dm_states = list(state.dm_battles.values())
    goblin_battle = next(
        dm for dm in dm_states if CharacterId("고블린") in dm.session.context.characters
    )
    orc_battle = next(
        dm for dm in dm_states if CharacterId("오크") in dm.session.context.characters
    )
    assert goblin_battle is not orc_battle
    assert CharacterId("오크") not in goblin_battle.session.context.characters
    assert CharacterId("고블린") not in orc_battle.session.context.characters
    assert CharacterId("전사1") in goblin_battle.session.context.characters
    assert CharacterId("전사2") in orc_battle.session.context.characters
