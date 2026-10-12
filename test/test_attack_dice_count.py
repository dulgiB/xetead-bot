import pytest
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeBattleMode
from bot.session import BattleSession, _parse_attack_dice_count


def test_parse_attack_dice_count_accepts_positive_integer():
    assert _parse_attack_dice_count("2") == 2


@pytest.mark.parametrize("raw", ["0", "-1", "abc"])
def test_parse_attack_dice_count_rejects_invalid_value(raw):
    with pytest.raises(ValueError):
        _parse_attack_dice_count(raw)


def test_main_battle_session_uses_configured_dice_count(monkeypatch):
    import bot.session as session_module

    monkeypatch.setattr(session_module, "ATTACK_DICE_COUNT", 2)

    assert BattleSession({}, {}).context.milestone_n == 2


@pytest.mark.parametrize("mode", list(PracticeBattleMode))
def test_practice_context_passes_dice_count_through(mode):
    context = PracticeBattlefieldContext({}, {}, mode=mode, milestone_n=3)

    assert context.milestone_n == 3
