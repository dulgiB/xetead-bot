"""필드 효과의 admin 커맨드와 봇 재기동 복원.

필드 효과는 지속 턴수가 없어 해제하기 전까지 유지된다. 그래서 (1) 올리는
것과 걷는 것이 한 쌍으로 있어야 하고, (2) 봇이 재기동해도 살아남아야 한다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.objects.buff.models import BuffData  # noqa: E402
from battle.objects.define import (  # noqa: E402
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
from battle.objects.skill.effects import SkillEffectAddBuff  # noqa: E402
from bot.commands.admin import build_field_meta, handle_admin_command  # noqa: E402
from bot.field_restore import _restore_field_effects  # noqa: E402
from bot.log_sheets import FieldBattleType, FieldRow  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.session import BattleSession  # noqa: E402
from helpers import get_test_preset  # noqa: E402

FIELD_EFFECT_ID = "FieldEffect"
CHARACTER_PASSIVE_ID = "PassiveSkill"
FIELD_BUFF_ID = "FieldBuff"


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


def _passives() -> dict[str, PassiveSkillData]:
    return {
        FIELD_EFFECT_ID: PassiveSkillData(
            id=FIELD_EFFECT_ID,
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
            description="",
        ),
        CHARACTER_PASSIVE_ID: PassiveSkillData(
            id=CHARACTER_PASSIVE_ID,
            trigger=PassiveSkillTrigger.ROUND_START,
            target_type=PassiveSkillTargetType.SELF,
            effects=[],
            description="",
        ),
    }


def _make_state(started: bool = True) -> BotState:
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
        passive_skill_dict=_passives(),
    )
    state.session.add_character(
        get_test_preset("아군"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    if started:
        state.session.start()
    return state


class TestAdminCommand:
    def test_add_puts_effect_on_the_field(self):
        state = _make_state()

        reply = handle_admin_command(f"[필드효과/{FIELD_EFFECT_ID}]", state).reply_text

        assert FIELD_EFFECT_ID in state.session.context.field_effects
        assert "필드 효과 발생" in reply

    def test_remove_takes_it_off(self):
        state = _make_state()
        handle_admin_command(f"[필드효과/{FIELD_EFFECT_ID}]", state)

        reply = handle_admin_command(
            f"[필드효과해제/{FIELD_EFFECT_ID}]", state
        ).reply_text

        assert FIELD_EFFECT_ID not in state.session.context.field_effects
        assert "필드 효과 해제" in reply

    def test_remove_is_not_swallowed_by_the_add_pattern(self):
        """ "필드효과해제"는 "필드효과" 패턴에도 걸리므로, 해제가 부여로
        잘못 라우팅되면 안 된다."""
        state = _make_state()
        state.session.context.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)

        handle_admin_command(f"[필드효과해제/{FIELD_EFFECT_ID}]", state)

        assert FIELD_EFFECT_ID not in state.session.context.field_effects

    def test_unknown_effect_is_reported(self):
        state = _make_state()

        reply = handle_admin_command("[필드효과/없는효과]", state).reply_text

        assert "없습니다" in reply

    def test_character_passive_is_rejected(self):
        state = _make_state()

        reply = handle_admin_command(
            f"[필드효과/{CHARACTER_PASSIVE_ID}]", state
        ).reply_text

        assert "필드 효과가 아닙니다" in reply
        assert len(state.session.context.field_effects) == 0

    def test_duplicate_add_is_reported(self):
        state = _make_state()
        handle_admin_command(f"[필드효과/{FIELD_EFFECT_ID}]", state)

        reply = handle_admin_command(f"[필드효과/{FIELD_EFFECT_ID}]", state).reply_text

        assert "이미" in reply

    def test_removing_absent_effect_is_reported(self):
        state = _make_state()

        reply = handle_admin_command(
            f"[필드효과해제/{FIELD_EFFECT_ID}]", state
        ).reply_text

        assert "걸려 있지 않습니다" in reply

    def test_underscores_in_the_name_survive_markdown(self):
        """답글은 마크다운으로 나가므로 밑줄이 섞인 id를 그대로 끼워 넣으면
        강조로 먹혀 이름이 깨진다(실제 인스턴스에서 확인)."""
        state = _make_state()
        state.session.context._passive_skill_dictionary["필드_효과_1"] = (
            PassiveSkillData(
                id="필드_효과_1",
                trigger=PassiveSkillTrigger.ROUND_START,
                target_type=PassiveSkillTargetType.FIELD_ALLY_SIDE,
                effects=[],
                description="",
            )
        )

        reply = handle_admin_command("[필드효과/필드_효과_1]", state).reply_text

        assert "필드\\_효과\\_1" in reply

    def test_unknown_name_is_also_escaped(self):
        state = _make_state()

        reply = handle_admin_command("[필드효과/없는_효과_1]", state).reply_text

        assert "없는\\_효과\\_1" in reply

    def test_requires_an_ongoing_battle(self):
        state = _make_state(started=False)

        reply = handle_admin_command(f"[필드효과/{FIELD_EFFECT_ID}]", state).reply_text

        assert "진행 중인 전투가 없습니다" in reply


class TestPersistence:
    def test_meta_carries_active_field_effects(self):
        state = _make_state()
        state.session.context.add_field_effect(
            FIELD_EFFECT_ID, FieldEffectSource.CHARM, "행운의 부적"
        )

        meta = build_field_meta(state)

        assert meta["field_effects"] == [
            {
                "id": FIELD_EFFECT_ID,
                "source": FieldEffectSource.CHARM.value,
                "source_detail": "행운의 부적",
            }
        ]

    def _row(self, field_effects: list[dict]) -> FieldRow:
        return FieldRow(
            field_id="1",
            battle_type=FieldBattleType.MAIN,
            round_n=2,
            phase="아군 행동",
            characters=[],
            meta={"name": "테스트", "field_effects": field_effects},
        )

    def test_restore_brings_effects_back(self):
        state = _make_state()
        row = self._row(
            [
                {
                    "id": FIELD_EFFECT_ID,
                    "source": FieldEffectSource.CHARM.value,
                    "source_detail": "행운의 부적",
                }
            ]
        )

        _restore_field_effects(state.session, row)

        restored = state.session.context.field_effects.get(FIELD_EFFECT_ID)
        assert restored is not None
        assert restored.source is FieldEffectSource.CHARM
        assert restored.source_detail == "행운의 부적"

    def test_restored_effect_applies_again(self):
        state = _make_state()
        row = self._row([{"id": FIELD_EFFECT_ID, "source": "관리자"}])

        _restore_field_effects(state.session, row)
        state.session.context.on_start_round()

        assert (
            state.session.context.buff_container.get_buff(
                CharacterId("아군"), FIELD_BUFF_ID
            )
            is not None
        )

    def test_broken_entry_does_not_block_the_rest(self):
        """시트에서 지워진 id 하나가 복원 전체를 막으면 안 된다."""
        state = _make_state()
        row = self._row(
            [
                {"id": "사라진효과", "source": "관리자"},
                {"id": FIELD_EFFECT_ID, "source": "관리자"},
            ]
        )

        _restore_field_effects(state.session, row)

        assert FIELD_EFFECT_ID in state.session.context.field_effects

    def test_missing_meta_key_is_fine(self):
        state = _make_state()
        row = FieldRow(
            field_id="1",
            battle_type=FieldBattleType.MAIN,
            round_n=1,
            phase="아군 행동",
            characters=[],
            meta={"name": "테스트"},
        )

        _restore_field_effects(state.session, row)

        assert len(state.session.context.field_effects) == 0
