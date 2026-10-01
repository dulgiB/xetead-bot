"""캐릭터의 체력 블라인드(hide_hp).

에너미와 같은 체크박스를 "캐릭터" 시트에도 두며, 본 전투와 대련 계열 모두
공개 출력에서 체력을 "?/?"로 가린다. 에너미와 달리 체력이 남은 채로 필드에서
빠질 수 있으므로(결투 기권 등), 빠진 뒤의 출력도 가려야 한다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_processors import process_ally_command
from battle.core.commands.parser import parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.define import (
    FATE_INTERVENTION_HP_COST,
    BattlefieldColumnIndex,
    FactionType,
)
from battle.objects.models import CharacterId
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeBattleMode, SideType
from bot.battle_reply_text import format_final_hp_roster, format_log_entry_block
from battle.core.commands.models import BattleLogEntry, BattleLogEntryKind
from helpers import get_test_preset
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet

HIDDEN = CharacterId("아군 1")
SHOWN = CharacterId("아군 2")


def _context() -> BattlefieldContext:
    context = BattlefieldContext(buff_dict={}, skill_dict={})
    context.add_character(
        get_test_preset(HIDDEN.name, initial_hp=70, hide_hp=True),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    context.add_character(
        get_test_preset(SHOWN.name, initial_hp=60),
        FactionType.ALLY,
        BattlefieldColumnIndex(1),
    )
    return context


def _damage_entry(name: str, hp_after: int) -> BattleLogEntry:
    return BattleLogEntry(
        target_name=name,
        kind=BattleLogEntryKind.DAMAGE,
        result="대미지 10",
        value=10,
        hp_after=hp_after,
        max_hp=100,
    )


def test_character_sheet_row_reads_hide_hp():
    row = {
        "name": HIDDEN.name,
        "mastodon_id": "",
        "curr_hp": 50,
        "max_hp": 100,
        "atk": 5,
        "attack_range": 3,
        "m_res": "보통",
        "is_magic": False,
        "max_cost": 3,
        "hide_hp": True,
        "revival_count": 0,
        "fate_date": "",
    }

    assert CombatCharacterDataFromSpreadsheet.from_dict(row).hide_hp is True


def test_final_roster_hides_only_flagged_character():
    roster = format_final_hp_roster(_context())

    assert f"▹ {HIDDEN.name} | ?/?" in roster
    assert f"▹ {SHOWN.name} | 60/100" in roster


def test_result_line_stays_hidden_after_leaving_the_field():
    """결투 기권자의 패배 대가처럼 필드에서 빠진 뒤에도 체력이 출력된다."""
    context = _context()
    context.force_remove_character(HIDDEN)

    block = format_log_entry_block(
        context,
        [_damage_entry(HIDDEN.name, 40), _damage_entry(SHOWN.name, 50)],
        "결투 패배 처리",
    )

    assert f"▹ {HIDDEN.name} | -10 → ?/?" in block
    assert f"▹ {SHOWN.name} | -10 → 50/100" in block


@pytest.mark.parametrize("mode", list(PracticeBattleMode))
def test_every_practice_mode_hides_hp(mode):
    context = PracticeBattlefieldContext(buff_dict={}, skill_dict={}, mode=mode)
    context.add_character(
        get_test_preset(HIDDEN.name, hide_hp=True),
        SideType.SIDE_1,
        BattlefieldColumnIndex(0),
    )
    context.add_character(
        get_test_preset(SHOWN.name), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )

    roster = format_final_hp_roster(context)

    assert f"▹ {HIDDEN.name} | ?/?" in roster
    assert f"▹ {SHOWN.name} | ?/?" not in roster


@pytest.mark.parametrize(("hide_hp", "shows_hp"), [(True, False), (False, True)])
def test_fate_hp_shortage_error_respects_hide_hp(hide_hp, shows_hp):
    context = BattlefieldContext(buff_dict={}, skill_dict={})
    context.add_character(
        get_test_preset(
            HIDDEN.name,
            initial_hp=FATE_INTERVENTION_HP_COST,
            revival_count=1,
            hide_hp=hide_hp,
        ),
        FactionType.ALLY,
        BattlefieldColumnIndex(3),
    )
    context.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(3)
    )
    command = parse_character_command(HIDDEN, "[공격+/적군 1]", context)
    assert command is not None

    with pytest.raises(CommandValidationError) as exc_info:
        process_ally_command(context, command)

    assert ("현재 체력" in str(exc_info.value)) is shows_hp
