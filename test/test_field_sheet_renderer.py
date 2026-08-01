from battle.core.battlefield_context import BattlefieldContext
from battle.objects.define import (
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.passive_skill.passive_skill import PassiveSkillWrapperBuff
from battle.objects.skill.effects import SkillEffectDamage
from bot.field_sheet_renderer import _format_buff_cell
from helpers import get_test_preset


def test_format_buff_cell_describes_passive_wrapped_buff_without_crashing():
    """패시브 스킬로 부여된 버프는 "버프" 시트가 아니라 "스킬_패시브" 시트
    출신이라 context.get_buff_data_by_id()로 조회하면 KeyError가 난다 —
    필드 시트 렌더링 중 이 조회가 일어나면 안 된다(대신 버프 자신의
    get_description()을 통해 설명을 얻어야 한다)."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    passive_data = PassiveSkillData(
        id="테스트 패시브",
        trigger=PassiveSkillTrigger.ON_ACTION,
        target_type=PassiveSkillTargetType.SELF,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 1, ValueType.INTEGER, None, None)
        ],
        description="테스트 패시브 설명",
    )
    ctx.buff_container.add_passive_wrapper(
        PassiveSkillWrapperBuff.create(ally_id, passive_data)[0]
    )

    display_text, note_text = _format_buff_cell(ctx, ally_id)

    assert "테스트 패시브" in display_text
    assert "테스트 패시브 설명" in note_text
