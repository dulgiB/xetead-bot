"""`[전투개시]` 때 합동 스킬 짝 설정이 어긋난 행을 admin에게 알리는 경고."""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.objects.skill.models import SkillData  # noqa: E402
from bot.commands.admin import _check_joint_skill_config  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.session import BattleSession  # noqa: E402
from helpers import get_test_preset  # noqa: E402


def _skill(skill_id: str, paired: tuple[str, ...]) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=3,
        effects=[],
        description="",
        paired_characters=paired,
        joint_unlocked=True,
    )


def _state(skills: list[SkillData]) -> BotState:
    state = BotState(
        char_dict={},
        name_dict={
            name: get_test_preset(name) for name in ("아군_1", "아군_2(테스트)")
        },
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    state.session = BattleSession(
        buff_dict={}, skill_dict={s.id: s for s in skills}, passive_skill_dict={}
    )
    return state


def test_valid_pair_produces_no_warning():
    assert (
        _check_joint_skill_config(_state([_skill("합동_1", ("아군_1", "아군_2"))]))
        is None
    )


def test_unknown_name_and_single_partner_are_reported():
    warning = _check_joint_skill_config(
        _state(
            [_skill("합동_1", ("아군_1", "없는_이름")), _skill("합동_2", ("아군_1",))]
        )
    )

    assert warning is not None
    assert "없는_이름" in warning
    assert "합동_2: 짝이 1명뿐입니다." in warning
