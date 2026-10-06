"""admin의 `[버프부여/대상/버프(/부여자)]` · `[버프해제/대상/버프(/부여자)]`.

부여자를 생략하면 "시스템"이 건다. 부여자가 전장의 캐릭터여야 동작하는
버프(도발 등)는 생략을 거부하고, 부여자와 무관한 버프(고정 지속 대미지 등)는
"시스템"이 걸어도 그대로 동작해야 한다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.core.commands.admin import ADMIN_ID  # noqa: E402
from battle.objects.buff.models import BuffData  # noqa: E402
from battle.objects.define import (  # noqa: E402
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueType,
)
from battle.objects.models import CharacterId  # noqa: E402
from bot.commands.admin import handle_admin_command  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.session import BattleSession  # noqa: E402
from helpers import get_test_preset  # noqa: E402

ATK_BUFF_ID = "공격 강화"
TAUNT_BUFF_ID = "유도"
DOT_BUFF_ID = "잔향: 테스트"
HOT_BUFF_ID = "재생"
IGNITE_BUFF_ID = "점화"
STACK_BUFF_ID = "표식"

ALLY_1 = CharacterId("아군 1")
ALLY_2 = CharacterId("아군 2")
ENEMY = CharacterId("적군 1")


def _buff(
    id_: str,
    class_name: str,
    value: int = 0,
    turns: int = 2,
    max_stack: int | None = None,
) -> BuffData:
    return BuffData(
        id=id_,
        buff_class_name=class_name,
        duration_turn_value=turns,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER if value else None,
        value=value,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.BUFF,
        description="",
        max_stack=max_stack,
    )


def _make_state(started: bool = True) -> BotState:
    state = BotState(
        char_dict={},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    buffs = [
        _buff(ATK_BUFF_ID, "BuffAtk", value=3),
        _buff(TAUNT_BUFF_ID, "BuffTaunt", turns=1),
        _buff(DOT_BUFF_ID, "BuffDamageOverTime", value=7),
        _buff(HOT_BUFF_ID, "BuffHealOverTime", value=5),
        _buff(IGNITE_BUFF_ID, "BuffDelayedColumnBurst", turns=1),
        _buff(STACK_BUFF_ID, "BuffStackingMark", turns=3, max_stack=3),
    ]
    state.session = BattleSession(buff_dict={b.id: b for b in buffs}, skill_dict={})
    state.session.add_character(
        get_test_preset(ALLY_1.name, max_hp=100),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    state.session.add_character(
        get_test_preset(ALLY_2.name, max_hp=100),
        FactionType.ALLY,
        BattlefieldColumnIndex(1),
    )
    state.session.add_character(
        get_test_preset(ENEMY.name, max_hp=100),
        FactionType.ENEMY,
        BattlefieldColumnIndex(3),
    )
    if started:
        state.session.start()
    return state


def _buffs_on(state: BotState, char_id: CharacterId, buff_id: str):
    assert state.session is not None
    return [
        b
        for b in state.session.context.buff_container.get_buffs_by(char_id, None)
        if b.id == buff_id
    ]


def _finish_round(state: BotState) -> None:
    assert state.session is not None
    state.session.context.on_finish_round()


class TestAdd:
    def test_omitted_giver_is_system(self):
        state = _make_state()

        reply = handle_admin_command(
            f"[버프부여/{ALLY_1.name}/{ATK_BUFF_ID}]", state
        ).reply_text

        [buff] = _buffs_on(state, ALLY_1, ATK_BUFF_ID)
        assert buff.given_by == ADMIN_ID
        assert "부여" in reply

    def test_names_and_keyword_ignore_whitespace(self):
        state = _make_state()

        handle_admin_command("[버프 부여/아군1/공격강화]", state)

        assert len(_buffs_on(state, ALLY_1, ATK_BUFF_ID)) == 1

    def test_giver_required_buff_rejects_missing_giver(self):
        state = _make_state()

        reply = handle_admin_command(
            f"[버프부여/{ENEMY.name}/{TAUNT_BUFF_ID}]", state
        ).reply_text

        assert _buffs_on(state, ENEMY, TAUNT_BUFF_ID) == []
        assert "부여자" in reply

    def test_giver_required_buff_uses_given_giver(self):
        state = _make_state()

        handle_admin_command(
            f"[버프부여/{ENEMY.name}/{TAUNT_BUFF_ID}/{ALLY_1.name}]", state
        )

        [buff] = _buffs_on(state, ENEMY, TAUNT_BUFF_ID)
        assert buff.given_by == ALLY_1
        assert buff.get_target_override() == ALLY_1

    def test_ignite_snapshots_the_target_column(self):
        state = _make_state()

        handle_admin_command(
            f"[버프부여/{ENEMY.name}/{IGNITE_BUFF_ID}/{ALLY_1.name}]", state
        )

        [buff] = _buffs_on(state, ENEMY, IGNITE_BUFF_ID)
        assert buff.value == BattlefieldColumnIndex(3).value


class TestSystemGivenOverTimeEffects:
    """부여자와 무관한 고정 지속 효과는 "시스템"이 걸어도 들어가야 한다 —
    전장에 없는 부여자를 "사망한 공격자"로 오인해 버리면 안 된다."""

    def test_damage_over_time_applies(self):
        state = _make_state()
        handle_admin_command(f"[버프부여/{ALLY_1.name}/{DOT_BUFF_ID}]", state)

        _finish_round(state)

        assert state.session is not None
        assert state.session.context.characters[ALLY_1].status.curr_hp == 93

    def test_heal_over_time_applies(self):
        state = _make_state()
        assert state.session is not None
        state.session.context.characters[ALLY_1].status.curr_hp = 50
        handle_admin_command(f"[버프부여/{ALLY_1.name}/{HOT_BUFF_ID}]", state)

        _finish_round(state)

        assert state.session.context.characters[ALLY_1].status.curr_hp == 55


class TestRemove:
    def test_removes_every_giver_by_default(self):
        state = _make_state()
        handle_admin_command(
            f"[버프부여/{ENEMY.name}/{TAUNT_BUFF_ID}/{ALLY_1.name}"
            f" - 버프부여/{ENEMY.name}/{TAUNT_BUFF_ID}/{ALLY_2.name}]",
            state,
        )

        reply = handle_admin_command(
            f"[버프해제/{ENEMY.name}/{TAUNT_BUFF_ID}]", state
        ).reply_text

        assert _buffs_on(state, ENEMY, TAUNT_BUFF_ID) == []
        assert reply.count("] 해제") == 2

    def test_giver_narrows_removal(self):
        state = _make_state()
        handle_admin_command(
            f"[버프부여/{ENEMY.name}/{TAUNT_BUFF_ID}/{ALLY_1.name}"
            f" - 버프부여/{ENEMY.name}/{TAUNT_BUFF_ID}/{ALLY_2.name}]",
            state,
        )

        handle_admin_command(
            f"[버프해제/{ENEMY.name}/{TAUNT_BUFF_ID}/{ALLY_1.name}]", state
        )

        [buff] = _buffs_on(state, ENEMY, TAUNT_BUFF_ID)
        assert buff.given_by == ALLY_2

    def test_missing_buff_is_reported(self):
        state = _make_state()

        reply = handle_admin_command(
            f"[버프해제/{ALLY_1.name}/{ATK_BUFF_ID}]", state
        ).reply_text

        assert "걸려 있지 않습니다" in reply


class TestReplyText:
    def test_repeated_add_is_merged_into_one_line(self):
        """같은 대상·버프·부여자에게 거듭 건 부여는 한 줄로 합쳐 최종값만 보인다."""
        state = _make_state()

        reply = handle_admin_command(
            f"[버프부여/{ENEMY.name}/{STACK_BUFF_ID}"
            f" - 버프부여/{ALLY_1.name}/{STACK_BUFF_ID}"
            f" - 버프부여/{ENEMY.name}/{STACK_BUFF_ID}]",
            state,
        ).reply_text

        assert reply == (
            "◊ 버프 적용\n\n"
            f"▹ {ENEMY.name} | [{STACK_BUFF_ID}]×2 부여 → 최종 2\n"
            f"▹ {ALLY_1.name} | [{STACK_BUFF_ID}]×1 부여 → 최종 1"
        )

    def test_different_givers_stay_separate(self):
        state = _make_state()

        reply = handle_admin_command(
            f"[버프부여/{ENEMY.name}/{STACK_BUFF_ID}/{ALLY_1.name}"
            f" - 버프부여/{ENEMY.name}/{STACK_BUFF_ID}/{ALLY_2.name}]",
            state,
        ).reply_text

        assert reply.count("×1 부여") == 2

    def test_remove_only_chain_uses_remove_header(self):
        state = _make_state()
        handle_admin_command(f"[버프부여/{ALLY_1.name}/{ATK_BUFF_ID}]", state)

        reply = handle_admin_command(
            f"[버프해제/{ALLY_1.name}/{ATK_BUFF_ID}]", state
        ).reply_text

        assert reply.startswith("◊ 버프 해제\n\n▹ ")


class TestChain:
    def test_mixed_chain_applies_in_order(self):
        state = _make_state()
        handle_admin_command(f"[버프부여/{ALLY_2.name}/{ATK_BUFF_ID}]", state)

        handle_admin_command(
            f"[버프부여/{ALLY_1.name}/{ATK_BUFF_ID}"
            f" - 버프해제/{ALLY_2.name}/{ATK_BUFF_ID}"
            f" - 버프부여/{ENEMY.name}/{DOT_BUFF_ID}]",
            state,
        )

        assert len(_buffs_on(state, ALLY_1, ATK_BUFF_ID)) == 1
        assert _buffs_on(state, ALLY_2, ATK_BUFF_ID) == []
        assert len(_buffs_on(state, ENEMY, DOT_BUFF_ID)) == 1

    def test_one_invalid_part_applies_nothing(self):
        state = _make_state()

        reply = handle_admin_command(
            f"[버프부여/{ALLY_1.name}/{ATK_BUFF_ID} - 버프부여/{ALLY_2.name}/없는버프]",
            state,
        ).reply_text

        assert _buffs_on(state, ALLY_1, ATK_BUFF_ID) == []
        assert "적용하지 않았습니다" in reply
        assert "없는버프" in reply

    def test_unknown_target_is_reported(self):
        state = _make_state()

        reply = handle_admin_command(
            f"[버프부여/없는캐릭터/{ATK_BUFF_ID}]", state
        ).reply_text

        assert "참여하고 있지 않습니다" in reply


def test_requires_started_battle():
    state = _make_state(started=False)

    reply = handle_admin_command(
        f"[버프부여/{ALLY_1.name}/{ATK_BUFF_ID}]", state
    ).reply_text

    assert reply == "◊ 진행 중인 전투가 없습니다."
