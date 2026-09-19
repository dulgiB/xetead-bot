"""필드 효과 표시: 필드 텍스트 요약과 답글 결과 줄."""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import BattleLogEntry, BattleLogEntryKind
from battle.objects.define import BattlefieldColumnIndex, FactionType
from battle.objects.field_effect.models import FieldEffectSource
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from bot.battle_reply_text import format_log_entry_block
from helpers import get_test_preset

EFFECT_ID = "FieldEffect"


def _effect(description: str = "전장이 불타오른다.") -> PassiveSkillData:
    return PassiveSkillData(
        id=EFFECT_ID,
        trigger=PassiveSkillTrigger.ROUND_START,
        target_type=PassiveSkillTargetType.FIELD_ALL,
        effects=[],
        description=description,
    )


def _make_context(description: str = "전장이 불타오른다.") -> BattlefieldContext:
    ctx = BattlefieldContext(
        buff_dict={},
        skill_dict={},
        passive_skill_dict={EFFECT_ID: _effect(description)},
    )
    ctx.add_character(
        get_test_preset("아군"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    return ctx


class TestFieldTextSummary:
    def test_active_effect_appears_with_description(self):
        ctx = _make_context()
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        text = ctx.format_field_text()

        assert "[필드 효과]" in text
        assert EFFECT_ID in text
        assert "전장이 불타오른다." in text

    def test_source_is_shown(self):
        """출처를 특정할 수 있으면 종류("부적")가 아니라 그 이름을 적는다 —
        어느 부적이 걸었는지가 더 쓸모 있다."""
        ctx = _make_context()
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.CHARM, "행운의 부적")

        text = ctx.format_field_text()

        assert f"{EFFECT_ID}[행운의 부적]" in text

    def test_source_falls_back_to_its_kind(self):
        ctx = _make_context()
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        text = ctx.format_field_text()

        assert f"{EFFECT_ID}[시스템]" in text

    def test_no_block_when_nothing_is_active(self):
        ctx = _make_context()

        assert "[필드 효과]" not in ctx.format_field_text()

    def test_effect_without_description_still_listed(self):
        ctx = _make_context(description="")
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        text = ctx.format_field_text()

        assert EFFECT_ID in text

    def test_removed_effect_disappears(self):
        ctx = _make_context()
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.remove_field_effect(EFFECT_ID)

        assert "[필드 효과]" not in ctx.format_field_text()


class TestReplyLine:
    def test_field_effect_entry_reads_as_an_event_not_a_target(self):
        """대상이 캐릭터가 아니라 전장이므로 "이름 | 결과" 형식이 아니다."""
        ctx = _make_context()
        entry = BattleLogEntry(
            target_name=EFFECT_ID,
            kind=BattleLogEntryKind.FIELD_EFFECT,
            result="필드 효과 발생",
        )

        block = format_log_entry_block(ctx, [entry], "정산")

        assert f"▹ 필드 효과 발생: {EFFECT_ID}" in block
