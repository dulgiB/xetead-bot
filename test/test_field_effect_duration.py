"""필드 효과의 지속 턴: 상시 효과와 일시 효과.

턴 수는 효과 행이 아니라 거는 쪽(admin 커맨드·스킬의 value_N)이 정한다.
일시 효과는 버프처럼 라운드 종료마다 1씩 줄다가 0이 되면 걷히고, 걷힐 때
그 효과가 부여한 버프도 함께 회수돼야 한다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.core.battlefield_context import BattlefieldContext  # noqa: E402
from battle.core.commands.admin import ChangePhaseCommand  # noqa: E402
from battle.core.commands.define import RoundPhaseType  # noqa: E402
from battle.core.commands.models import (  # noqa: E402
    FIELD_EFFECT_ADDED_RESULT,
    FIELD_EFFECT_REMOVED_RESULT,
    BattleLogEntry,
    BattleLogEntryKind,
)
from battle.core.commands.parser import parse_character_command  # noqa: E402
from battle.core.round_manager import RoundManager  # noqa: E402
from battle.objects.buff.models import BuffData  # noqa: E402
from battle.objects.define import (  # noqa: E402
    ActionType,
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueType,
)
from battle.objects.field_effect.models import FieldEffectSource  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from battle.objects.passive_skill.models import (  # noqa: E402
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import (  # noqa: E402
    SkillEffectAddBuff,
    SkillEffectAddFieldEffect,
)
from battle.objects.skill.models import SkillData  # noqa: E402
from bot.battle_reply_text import format_log_entry_block  # noqa: E402
from bot.commands.admin import build_field_meta, handle_admin_command  # noqa: E402
from bot.field_restore import _restore_field_effects  # noqa: E402
from bot.log_sheets import FieldBattleType, FieldRow  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.session import BattleSession  # noqa: E402
from helpers import get_test_preset  # noqa: E402

FIELD_EFFECT_ID = "FieldEffect"
OTHER_EFFECT_ID = "OtherFieldEffect"
FIELD_BUFF_ID = "FieldBuff"
ADD_SKILL_ID = "스킬_1"


def _field_buff() -> BuffData:
    return BuffData(
        id=FIELD_BUFF_ID,
        buff_class_name="BuffAtk",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=10,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.BUFF,
        description="",
    )


def _field_effect(effect_id: str = FIELD_EFFECT_ID) -> PassiveSkillData:
    return PassiveSkillData(
        id=effect_id,
        trigger=PassiveSkillTrigger.ROUND_START,
        target_type=PassiveSkillTargetType.FIELD_ALLY_SIDE,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=FIELD_BUFF_ID,
                buff_add_timing=None,
            )
        ],
        description="아군 전원에게 버프를 건다.",
    )


def _add_skill(turns: int | None) -> SkillData:
    return SkillData(
        id=ADD_SKILL_ID,
        target_rule="SkillTargetRuleSelf",
        cost=1,
        target_count=1,
        effects=[
            SkillEffectAddFieldEffect(
                value_source=None,
                value=turns,
                value_type=None,
                buff_id=None,
                buff_add_timing=None,
                field_effect_id=FIELD_EFFECT_ID,
            )
        ],
        description="",
    )


def _make_context(skill_turns: int | None = None) -> BattlefieldContext:
    ctx = BattlefieldContext(
        buff_dict={FIELD_BUFF_ID: _field_buff()},
        skill_dict={ADD_SKILL_ID: _add_skill(skill_turns)},
        passive_skill_dict={
            FIELD_EFFECT_ID: _field_effect(),
            OTHER_EFFECT_ID: _field_effect(OTHER_EFFECT_ID),
        },
    )
    ctx.add_character(
        get_test_preset("시전자", skill_1_id=ADD_SKILL_ID),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return ctx


def _has_field_buff(ctx: BattlefieldContext) -> bool:
    return ctx.buff_container.get_buff(CharacterId("시전자"), FIELD_BUFF_ID) is not None


def _field_effect_entries(entries: list[BattleLogEntry]) -> list[BattleLogEntry]:
    return [e for e in entries if e.kind == BattleLogEntryKind.FIELD_EFFECT]


class TestCountdown:
    def test_temporary_effect_lasts_the_given_number_of_rounds(self):
        """버프와 같이 부여한 라운드를 1턴으로 센다 — 2턴이면 이번 라운드와
        다음 라운드 끝까지 유지된다."""
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN, turns=2)

        ctx.on_finish_round()
        effect = ctx.field_effects.get(FIELD_EFFECT_ID)
        assert effect is not None
        assert effect.remaining_turns == 1

        ctx.on_finish_round()
        assert FIELD_EFFECT_ID not in ctx.field_effects

    def test_expiry_takes_back_the_buffs_it_gave(self):
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN, turns=1)
        ctx.on_start_round()
        assert _has_field_buff(ctx)

        ctx.on_finish_round()

        assert not _has_field_buff(ctx)

    def test_expiry_is_reported_with_the_round_end_entries(self):
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN, turns=1)

        entries, _ = ctx.on_finish_round()

        expired = _field_effect_entries(entries)
        assert [(e.target_name, e.result) for e in expired] == [
            (FIELD_EFFECT_ID, FIELD_EFFECT_REMOVED_RESULT)
        ]

    def test_permanent_effect_is_untouched_by_round_end(self):
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)

        for _ in range(5):
            entries, _ = ctx.on_finish_round()
            assert _field_effect_entries(entries) == []

        effect = ctx.field_effects.get(FIELD_EFFECT_ID)
        assert effect is not None
        assert effect.remaining_turns is None


class TestReapply:
    def test_reapplying_a_temporary_effect_resets_its_turns(self):
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN, turns=1)

        refreshed = ctx.add_field_effect(
            FIELD_EFFECT_ID, FieldEffectSource.SKILL, turns=3
        )

        assert refreshed is not None
        assert refreshed.remaining_turns == 3
        assert len(ctx.field_effects) == 1

    def test_permanent_reapply_makes_a_temporary_effect_permanent(self):
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.SKILL, turns=1)

        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.on_finish_round()

        assert FIELD_EFFECT_ID in ctx.field_effects

    def test_temporary_reapply_leaves_a_permanent_effect_alone(self):
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)

        assert (
            ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.SKILL, turns=1)
            is None
        )
        ctx.on_finish_round()

        effect = ctx.field_effects.get(FIELD_EFFECT_ID)
        assert effect is not None
        assert effect.remaining_turns is None

    def test_refresh_does_not_stack_the_buffs(self):
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN, turns=1)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN, turns=2)
        ctx.on_start_round()

        buffs = [
            b
            for b in ctx.buff_container.get_buffs_by(CharacterId("시전자"), None)
            if b.id == FIELD_BUFF_ID
        ]
        assert len(buffs) == 1


def _use_add_skill(ctx: BattlefieldContext) -> None:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.process_command(
        parse_character_command(CharacterId("시전자"), f"[{ADD_SKILL_ID}/시전자]", ctx)
    )


class TestSkill:
    def test_value_sets_the_turns(self):
        ctx = _make_context(skill_turns=3)

        _use_add_skill(ctx)

        effect = ctx.field_effects.get(FIELD_EFFECT_ID)
        assert effect is not None
        assert effect.remaining_turns == 3

    def test_empty_value_keeps_it_permanent(self):
        ctx = _make_context(skill_turns=None)

        _use_add_skill(ctx)

        effect = ctx.field_effects.get(FIELD_EFFECT_ID)
        assert effect is not None
        assert effect.remaining_turns is None

    def test_reply_line_shows_the_turns(self):
        ctx = _make_context(skill_turns=3)
        _use_add_skill(ctx)

        entries = _field_effect_entries(
            [entry for result in ctx.results for entry in result.log_entries]
        )
        assert [e.result for e in entries] == [f"{FIELD_EFFECT_ADDED_RESULT} (3턴)"]

        block = format_log_entry_block(ctx, entries, "결과")
        assert f"▹ 필드 효과 **「{FIELD_EFFECT_ID}」** 적용 (3턴)" in block


class TestDisplay:
    def test_label_carries_remaining_turns(self):
        ctx = _make_context()
        effect = ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN, turns=2)

        assert effect is not None
        assert effect.display_label() == f"{FIELD_EFFECT_ID}[시스템] (2턴)"

    def test_permanent_effects_are_listed_before_temporary_ones(self):
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN, turns=2)
        ctx.add_field_effect(OTHER_EFFECT_ID, FieldEffectSource.ADMIN)

        assert [e.id for e in ctx.field_effects.as_display_list()] == [
            OTHER_EFFECT_ID,
            FIELD_EFFECT_ID,
        ]


def _make_state() -> BotState:
    state = BotState(
        char_dict={},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    state.session = BattleSession(
        buff_dict={FIELD_BUFF_ID: _field_buff()},
        skill_dict={},
        passive_skill_dict={FIELD_EFFECT_ID: _field_effect()},
    )
    state.session.add_character(
        get_test_preset("아군"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    state.session.start()
    return state


class TestAdmin:
    def test_turns_argument_makes_it_temporary(self):
        state = _make_state()

        reply = handle_admin_command(
            f"[필드효과/{FIELD_EFFECT_ID}/3]", state
        ).reply_text

        effect = state.session.context.field_effects.get(FIELD_EFFECT_ID)
        assert effect is not None
        assert effect.remaining_turns == 3
        assert reply.startswith(f"◊ 필드 효과 **「{FIELD_EFFECT_ID}」** 적용 (3턴)")

    def test_without_turns_it_stays_permanent(self):
        state = _make_state()

        handle_admin_command(f"[필드효과/{FIELD_EFFECT_ID}]", state)

        effect = state.session.context.field_effects.get(FIELD_EFFECT_ID)
        assert effect is not None
        assert effect.remaining_turns is None

    def test_invalid_turns_are_rejected(self):
        state = _make_state()

        for bad in ("0", "세", "-1"):
            reply = handle_admin_command(
                f"[필드효과/{FIELD_EFFECT_ID}/{bad}]", state
            ).reply_text
            assert "1 이상의 정수" in reply

        assert len(state.session.context.field_effects) == 0


class TestPersistence:
    def test_remaining_turns_survive_a_restart(self):
        state = _make_state()
        state.session.context.add_field_effect(
            FIELD_EFFECT_ID, FieldEffectSource.SKILL, "시전자_1", turns=3
        )
        state.session.context.on_finish_round()
        meta = build_field_meta(state)
        assert meta["field_effects"][0]["remaining_turns"] == 2

        restored_state = _make_state()
        _restore_field_effects(
            restored_state.session,
            FieldRow(
                field_id="1",
                battle_type=FieldBattleType.MAIN,
                round_n=2,
                phase="아군 행동",
                characters=[],
                meta=meta,
            ),
        )

        effect = restored_state.session.context.field_effects.get(FIELD_EFFECT_ID)
        assert effect is not None
        assert effect.remaining_turns == 2
