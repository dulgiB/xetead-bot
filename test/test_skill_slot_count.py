"""스킬 슬롯은 `skill_1_id`~`skill_7_id`까지 읽는다(`MAX_SKILL_SLOT_COUNT`).

에너미가 스킬을 7개까지 쓰기 위한 상한이다. "캐릭터" 시트처럼 뒤쪽 열이 없는
행은 빈 슬롯으로 읽혀 기존과 같이 동작해야 한다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.parser import parse_character_command
from battle.objects.define import (
    MAX_SKILL_SLOT_COUNT,
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.models import SkillData
from helpers import get_test_preset
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet

_SKILL_IDS = [f"스킬_{i}" for i in range(1, 8)]


def _raw(**overrides) -> dict:
    base = {
        "name": "에너미_1",
        "mastodon_id": "",
        "curr_hp": 100,
        "max_hp": 100,
        "atk": 5,
        "attack_range": 3,
        "m_res": "보통",
        "is_magic": False,
        "max_cost": 3,
    }
    base.update(overrides)
    return base


def _dummy_skill(skill_id: str) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[],
        description="",
    )


def test_skill_slot_limit_is_seven():
    assert MAX_SKILL_SLOT_COUNT == 7


def test_from_dict_reads_up_to_skill_7_id():
    row = _raw(**{f"skill_{i}_id": sid for i, sid in enumerate(_SKILL_IDS, start=1)})
    data = CombatCharacterDataFromSpreadsheet.from_dict(row)
    assert data.skill_id_list == _SKILL_IDS


def test_missing_trailing_slot_columns_read_as_empty():
    data = CombatCharacterDataFromSpreadsheet.from_dict(
        _raw(skill_1_id="스킬_1", skill_2_id="스킬_2", skill_3_id="스킬_3")
    )
    assert data.skill_id_list == ["스킬_1", "스킬_2", "스킬_3", "", "", "", ""]


def test_seventh_slot_skill_is_built_and_declarable():
    ctx = BattlefieldContext(
        buff_dict={}, skill_dict={sid: _dummy_skill(sid) for sid in _SKILL_IDS}
    )
    ctx.add_character(
        get_test_preset(
            "에너미_1",
            is_enemy=True,
            **{f"skill_{i}_id": sid for i, sid in enumerate(_SKILL_IDS, start=1)},
        ),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    enemy = ctx.characters[CharacterId("에너미_1")]
    assert [s.data.id for s in enemy.skills] == _SKILL_IDS

    command = parse_character_command(CharacterId("에너미_1"), "[스킬_7/대상]", ctx)
    assert command is not None
    assert command.parts[0].type_ == ActionType.SKILL
    assert command.parts[0].skill_id == "스킬_7"
