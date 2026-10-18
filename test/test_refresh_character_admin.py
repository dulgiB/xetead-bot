"""[갱신/이름] — 전투 중 시트에서 고친 스탯을 전장에 다시 들이는 admin 커맨드.

스탯·스킬·패시브는 배치 때 한 번 복사되므로, 이 커맨드가 아니면 전투 도중의
시트 수정이 전장에 들어오지 않는다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.objects.buff.models import BuffData  # noqa: E402
from battle.objects.define import (  # noqa: E402
    BattlefieldColumnIndex,
    BuffType,
    CombatStatType,
    FactionType,
    MagicResistanceType,
    ValueType,
)
from battle.objects.models import CharacterId  # noqa: E402
from battle.objects.passive_skill.models import (  # noqa: E402
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import SkillEffectAddBuff  # noqa: E402
from bot.commands.admin import handle_admin_command  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.session import BattleSession  # noqa: E402
from helpers import get_test_preset  # noqa: E402

NAME = "아군"
CHAR_ID = CharacterId(NAME)
PASSIVE_BUFF_ID = "PassiveBuff"


def _passive_buff() -> BuffData:
    return BuffData(
        id=PASSIVE_BUFF_ID,
        buff_class_name="BuffAtk",
        duration_turn_value=1,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=1,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.BUFF,
        description="",
    )


def _passive(passive_id: str) -> PassiveSkillData:
    # 효과가 없는 패시브는 래퍼가 등록되지 않으므로 효과를 하나 싣는다.
    return PassiveSkillData(
        id=passive_id,
        trigger=PassiveSkillTrigger.ROUND_START,
        target_type=PassiveSkillTargetType.SELF,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=PASSIVE_BUFF_ID,
                buff_add_timing=None,
            )
        ],
        description="",
    )


def _make_state(skill_strong_attack, **preset) -> BotState:
    state = BotState(
        char_dict={},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    state.session = BattleSession(
        buff_dict={PASSIVE_BUFF_ID: _passive_buff()},
        skill_dict={skill_strong_attack.id: skill_strong_attack},
        passive_skill_dict={
            "PassiveSkill": _passive("PassiveSkill"),
            "PassiveSkill2": _passive("PassiveSkill2"),
        },
    )
    data = get_test_preset(NAME, **preset)
    state.name_dict[NAME] = data
    state.session.add_character(data, FactionType.ALLY, BattlefieldColumnIndex(0))
    state.session.start()
    return state


def _character(state: BotState):
    return state.session.context.characters[CHAR_ID]


def test_refresh_applies_sheet_stats(skill_strong_attack):
    state = _make_state(skill_strong_attack)
    state.name_dict[NAME] = get_test_preset(
        NAME,
        atk=8,
        attack_range=2,
        max_hp=120,
        m_res=MagicResistanceType.STRONG,
        is_magic_attacker=True,
        skill_1_id=skill_strong_attack.id,
        passive_skill_id="PassiveSkill",
    )

    reply = handle_admin_command(f"[갱신/{NAME}]", state).reply_text

    status = _character(state).status
    assert status[CombatStatType.ATK] == 8
    assert status[CombatStatType.RANGE] == 2
    assert status[CombatStatType.MAX_HP] == 120
    assert status.magic_resistance_type is MagicResistanceType.STRONG
    assert status.is_magic_attacker is True
    assert [s.data.id for s in _character(state).skills] == [skill_strong_attack.id]
    assert {w.id for w in state.session.context.passive_wrappers_of(CHAR_ID)} == {
        "PassiveSkill"
    }
    assert "공격력 5 → 8" in reply
    assert "사거리 3 → 2" in reply


def test_refresh_keeps_buff_offsets_and_remaining_cost(skill_strong_attack):
    """필드 효과 증감과 이번 라운드 남은 코스트는 시트가 아니라 전장의 상태다."""
    state = _make_state(skill_strong_attack)
    status = _character(state).status
    status.add_stat_offset(CombatStatType.ATK, 2)
    status.remaining_cost = 1
    state.name_dict[NAME] = get_test_preset(NAME, atk=8, max_cost=4)

    handle_admin_command(f"[갱신/{NAME}]", state)

    assert status[CombatStatType.ATK] == 10
    assert status.remaining_cost == 1
    assert status[CombatStatType.COST_PER_TURN] == 4


def test_refresh_adopts_sheet_hp_only_when_sheet_changed(skill_strong_attack):
    """체력은 봇이 마지막으로 읽거나 쓴 값과 시트가 다를 때만 들인다 — 전장
    체력과 비교하면 시트 쓰기가 실패한 대미지가 되돌려진다."""
    state = _make_state(skill_strong_attack)
    _character(state).status.curr_hp = 70  # 정산됐지만 시트 쓰기는 실패한 상태

    handle_admin_command(f"[갱신/{NAME}]", state)
    assert _character(state).status.curr_hp == 70

    state.name_dict[NAME] = get_test_preset(NAME, initial_hp=40)
    handle_admin_command(f"[갱신/{NAME}]", state)
    assert _character(state).status.curr_hp == 40


def test_refresh_clamps_hp_to_new_max(skill_strong_attack):
    state = _make_state(skill_strong_attack)
    state.name_dict[NAME] = get_test_preset(NAME, max_hp=50, initial_hp=100)

    handle_admin_command(f"[갱신/{NAME}]", state)

    assert _character(state).status.curr_hp == 50


def test_refresh_swaps_passive_only_when_id_changes(skill_strong_attack):
    state = _make_state(skill_strong_attack, passive_skill_id="PassiveSkill")
    context = state.session.context
    original = context.passive_wrappers_of(CHAR_ID)

    handle_admin_command(f"[갱신/{NAME}]", state)
    assert context.passive_wrappers_of(CHAR_ID) == original

    state.name_dict[NAME] = get_test_preset(NAME, passive_skill_id="PassiveSkill2")
    handle_admin_command(f"[갱신/{NAME}]", state)
    assert {w.id for w in context.passive_wrappers_of(CHAR_ID)} == {"PassiveSkill2"}


def test_unknown_skill_rejects_whole_refresh(skill_strong_attack):
    state = _make_state(skill_strong_attack)
    state.name_dict[NAME] = get_test_preset(NAME, atk=9, skill_1_id="없는스킬")

    reply = handle_admin_command(f"[갱신/{NAME}]", state).reply_text

    assert "갱신 실패" in reply
    assert _character(state).status[CombatStatType.ATK] == 5


def test_no_change_is_reported(skill_strong_attack):
    state = _make_state(skill_strong_attack)

    reply = handle_admin_command(f"[갱신/{NAME}]", state).reply_text

    assert reply == f"◊ {NAME} 갱신: 바뀐 값 없음"


def test_character_not_on_field(skill_strong_attack):
    state = _make_state(skill_strong_attack)

    reply = handle_admin_command("[갱신/없는캐릭터]", state).reply_text

    assert "전투에 참여하고 있지 않습니다" in reply


def test_requires_running_main_battle():
    state = BotState(
        char_dict={},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )

    reply = handle_admin_command(f"[갱신/{NAME}]", state).reply_text

    assert reply == "◊ 진행 중인 전투가 없습니다."
