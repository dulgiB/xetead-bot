from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import CharacterCommand, CommandPart
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.buffs import BuffGivenDamage
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import BuffUid, CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.passive_skill.passive_skill import PassiveSkillWrapperBuff
from battle.objects.skill.effects import SkillEffectAddBuff, SkillEffectDamage
from bot.field_sheet_renderer import (
    _ALLY_MAIN_ROW_START,
    _build_faction_block,
    _format_buff_cell,
)
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


def test_format_buff_cell_dedupes_passive_with_both_buff_mod_and_effects():
    """패시브 스킬 하나가 buff_mod_event(즉시 수치 보정)와 effects(트리거
    발동 효과)를 동시에 가지면 PassiveSkillWrapperBuff.create()가 역할별로
    나뉜 버프 인스턴스 2개를 반환한다 — 실제 게임 로직상 필요한 분리지만,
    필드 시트에는 같은 패시브 스킬 하나로만 보여야 한다(중복 표시 방지)."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    buff_mod_template = BuffGivenDamage._create_bare(
        id_="이중 역할 패시브",
        uid=BuffUid(ally_id, ally_id, "BuffGivenDamage"),
        given_by=ally_id,
        applied_to=ally_id,
        value=-60,
        value_type=ValueType.PERCENT,
    )
    passive_data = PassiveSkillData(
        id="이중 역할 패시브",
        trigger=PassiveSkillTrigger.ROUND_END,
        target_type=PassiveSkillTargetType.SELF,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=None,
                buff_add_timing=None,
            )
        ],
        description="이중 역할 패시브 설명",
        buff_mod_event=buff_mod_template.create_event(),
    )
    wrappers = PassiveSkillWrapperBuff.create(ally_id, passive_data)
    assert len(wrappers) == 2  # buff_mod 역할 1개 + effects 역할 1개
    for wrapper in wrappers:
        ctx.buff_container.add_passive_wrapper(wrapper)

    display_text, note_text = _format_buff_cell(ctx, ally_id)

    assert display_text.count("이중 역할 패시브") == 1
    assert note_text.count("이중 역할 패시브 설명") == 1


def _make_passive_with_referenced_buff_line(
    ally_id: CharacterId,
) -> PassiveSkillWrapperBuff:
    passive_data = PassiveSkillData(
        id="테스트 패시브",
        trigger=PassiveSkillTrigger.ON_ACTION,
        target_type=PassiveSkillTargetType.SELF,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 1, ValueType.INTEGER, None, None)
        ],
        description=("설명 본문.\n▸ [보조 버프]: 보조 버프의 개별 설명입니다."),
    )
    return PassiveSkillWrapperBuff.create(ally_id, passive_data)[0]


def test_referenced_buff_line_kept_when_not_yet_granted():
    """패시브 description의 "▸ [버프id]: ..." 줄은, 그 버프가 아직 부여되지
    않은 상태에서는 무엇을 부여하는지 보여주는 미리보기이므로 그대로 남아야
    한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.buff_container.add_passive_wrapper(
        _make_passive_with_referenced_buff_line(ally_id)
    )

    _display_text, note_text = _format_buff_cell(ctx, ally_id)

    assert "▸ [보조 버프]: 보조 버프의 개별 설명입니다." in note_text


def test_referenced_buff_line_stripped_once_buff_is_granted():
    """ "▸ [버프id]: ..." 줄이 가리키는 버프가 실제로 부여되고 나면, 그
    버프가 자기 자신의 note 줄을 따로 갖게 되어 같은 설명이 두 번
    보인다 — 부여된 뒤에는 패시브 쪽 미리보기 줄을 생략해야 한다."""
    ctx = BattlefieldContext(
        buff_dict={
            "보조 버프": BuffData(
                id="보조 버프",
                buff_class_name="BuffGivenDamage",
                duration_turn_value=2,
                duration_count_value=None,
                duration_count_deduct_condition=None,
                value_type=ValueType.PERCENT,
                value=10,
                condition_=None,
                condition_value=None,
                is_debuff=False,
                description="보조 버프의 개별 설명입니다.",
            )
        },
        skill_dict={},
    )
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.buff_container.add_passive_wrapper(
        _make_passive_with_referenced_buff_line(ally_id)
    )
    ctx.buff_container.add(
        BuffAddData(given_by=ally_id, applied_to=ally_id, buff_id="보조 버프")
    )

    _display_text, note_text = _format_buff_cell(ctx, ally_id)

    assert "▸ [보조 버프]: 보조 버프의 개별 설명입니다." not in note_text
    # "보조 버프" 자신의 note 줄에는 여전히 전체 설명이 정확히 한 번 나와야 한다.
    assert note_text.count("보조 버프의 개별 설명입니다.") == 1


def test_build_faction_block_pushes_remaining_slots_forward_after_removal():
    """같은 열 3슬롯 중 앞(슬롯0)에 있던 캐릭터가 전장에서 제거되면, 남은
    캐릭터들이 슬롯 번호 그대로(1, 2번 슬롯) 렌더링되어 앞자리가 빈칸으로
    보이면 안 된다 — 슬롯 인덱스와 무관하게 남은 순서대로 앞부터 채워야
    한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    column = BattlefieldColumnIndex(0)
    for name in ("A", "B", "C"):
        ctx.add_character(get_test_preset(name), FactionType.ALLY, column)
    ctx.remove_character(CharacterId("A"))  # 슬롯0을 비움 → {1: B, 2: C}

    grid, _declare_text, _notes = _build_faction_block(
        ctx,
        FactionType.ALLY,
        main_row_start=_ALLY_MAIN_ROW_START,
        direction=1,
        declared={},
    )

    assert "B" in grid[0][0]
    assert "C" in grid[3][0]
    assert grid[6][0] == ""


def test_build_faction_block_joins_declared_commands_into_single_text():
    """선언 내용은 더 이상 행별 그리드가 아니라, 적이 아무리 많아도 병합된
    셀 하나에 "이름 [커맨드]" 줄을 `\\n`으로 이어붙인 문자열 하나로
    반환되어야 한다(그리드였다면 슬롯 수를 넘는 적이 있을 때 구조가
    깨졌다)."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    enemy_ids = []
    for i in range(5):
        name = f"적{i}"
        column = BattlefieldColumnIndex(i // 3)  # 열당 최대 3명 제한 회피
        ctx.add_character(get_test_preset(name), FactionType.ENEMY, column)
        enemy_ids.append(CharacterId(name))

    declared = {
        enemy_id: [
            CharacterCommand(
                user_id=enemy_id,
                parts=[
                    CommandPart(
                        type_=ActionType.ATTACK, targets=[CharacterId("아군 1")]
                    )
                ],
            )
        ]
        for enemy_id in enemy_ids
    }

    _grid, declare_text, _notes = _build_faction_block(
        ctx,
        FactionType.ENEMY,
        main_row_start=_ALLY_MAIN_ROW_START,
        direction=1,
        declared=declared,
    )

    lines = declare_text.split("\n")
    assert len(lines) == 5
    assert lines[0] == "적0 [공격/아군 1]"
    assert lines[4] == "적4 [공격/아군 1]"
