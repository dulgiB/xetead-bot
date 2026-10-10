"""적 선언(PRE) 답글의 버프 부여 줄이 실제 부여 시점을 반영하는지.

정산(POST)으로 미뤄진 부여는 선언 시점에 아직 걸리지 않았고, 대상이 사거리
밖으로 빠지거나 시전자가 쓰러지면 끝내 걸리지 않는다. 선언 답글이 이를
"[X] 부여"로 적으면 플레이어가 이미 걸린 것으로 읽는다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import BattleLogEntryKind
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

_ENEMY = CharacterId("적군")
_ALLY = CharacterId("아군")


def _buff_row(buff_id: str, buff_name: str, value: int) -> BuffData:
    return BuffData.from_dict(
        {
            "id": buff_id,
            "buff_name": buff_name,
            "duration_turn_value": 2,
            "duration_count_value": "",
            "duration_count_deduct_condition": "",
            "value_type_0": "정수"
            if buff_name == "BuffReduceCostNextRound"
            else "퍼센트",
            "value_0": value,
            "condition": "",
            "condition_value": "",
            "type": "디버프",
            "description": "",
        }
    )


def _context() -> BattlefieldContext:
    buffs = {
        "표식_테스트": _buff_row("표식_테스트", "BuffReceivedDamage", 10),
        "코스트감소_테스트": _buff_row(
            "코스트감소_테스트", "BuffReduceCostNextRound", 1
        ),
    }
    skills = {
        # 대미지 + 표식 보유 대상에게 정산 시점 디버프
        "Cost2Skill": SkillData.from_dict(
            {
                "id": "Cost2Skill",
                "target_rule": "SkillTargetRuleNamed",
                "target_count": 1,
                "cost": 2,
                "effect_0": "SkillEffectDamage",
                "value_source_0": "고정값",
                "value_0": 10,
                "value_type_0": "정수",
                "effect_1": "SkillEffectAddBuffIfTargetHasReferencedBuff",
                "buff_name_1": "코스트감소_테스트",
                "reference_buff_id_1": "표식_테스트",
                "buff_add_timing_1": "적 공격 정산",
                "description": "",
            }
        ),
        # 대미지 없는 열 디버프, 부여 시점만 다르게
        "ColumnSkillPost": SkillData.from_dict(
            {
                "id": "ColumnSkillPost",
                "target_rule": "SkillTargetRuleColumn",
                "target_count": 1,
                "cost": 2,
                "effect_0": "SkillEffectAddBuff",
                "buff_name_0": "표식_테스트",
                "buff_add_timing_0": "적 공격 정산",
                "description": "",
            }
        ),
        "ColumnSkillPre": SkillData.from_dict(
            {
                "id": "ColumnSkillPre",
                "target_rule": "SkillTargetRuleColumn",
                "target_count": 1,
                "cost": 2,
                "effect_0": "SkillEffectAddBuff",
                "buff_name_0": "표식_테스트",
                "buff_add_timing_0": "적 행동 선언",
                "description": "",
            }
        ),
    }
    ctx = BattlefieldContext(buff_dict=buffs, skill_dict=skills)
    ctx.add_character(
        get_test_preset("아군"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset(
            "적군",
            max_cost=4,
            skill_1_id="Cost2Skill",
            skill_2_id="ColumnSkillPost",
            skill_3_id="ColumnSkillPre",
        ),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    return ctx


def _buff_add_results(ctx: BattlefieldContext) -> list[str]:
    return [
        entry.result
        for part in ctx.results
        for entry in part.log_entries
        if entry.kind == BattleLogEntryKind.BUFF_ADD
    ]


def test_deferred_buff_on_attack_is_previewed_as_conditional():
    ctx = _context()
    ctx.buff_container.add(
        BuffAddData(given_by=_ENEMY, applied_to=_ALLY, buff_id="표식_테스트")
    )
    manager = RoundManager(ctx)

    manager.process_command(parse_character_command(_ENEMY, "[Cost2Skill/아군]", ctx))

    assert _buff_add_results(ctx) == ["공격 성공 시 [코스트감소_테스트] 부여"]
    assert ctx.get_buff_stack(_ALLY, "코스트감소_테스트") == 0

    ctx.results.clear()
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert _buff_add_results(ctx) == ["[코스트감소_테스트] 부여 (2턴)"]
    assert ctx.get_buff_stack(_ALLY, "코스트감소_테스트") == 1


def test_deferred_buff_without_damage_is_previewed_as_on_resolution():
    ctx = _context()
    manager = RoundManager(ctx)

    manager.process_command(parse_character_command(_ENEMY, "[ColumnSkillPost/1]", ctx))

    assert _buff_add_results(ctx) == ["정산 시 [표식_테스트] 부여"]
    assert ctx.get_buff_stack(_ALLY, "표식_테스트") == 0


def test_buff_applied_on_declaration_keeps_plain_label():
    ctx = _context()
    manager = RoundManager(ctx)

    manager.process_command(parse_character_command(_ENEMY, "[ColumnSkillPre/1]", ctx))

    assert _buff_add_results(ctx) == ["[표식_테스트] 부여 (2턴)"]
    assert ctx.get_buff_stack(_ALLY, "표식_테스트") == 1
