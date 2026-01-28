import logging
import os
from typing import Optional

import discord
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from spreadsheets.models.battle import CharacterDataFromSpreadsheet

from bots.discord_bot.consts import (
    CLEANUP_INTERVAL_MINUTES,
    PHASE_NAMES,
    SESSION_TIMEOUT_SECONDS,
    SKILL_HELP,
    STAT_RULES,
)
from bots.discord_bot.load_data import load_spreadsheet_data
from bots.discord_bot.parse_helpers import (
    parse_attack_type,
    parse_m_res,
    validate_stats,
)
from bots.discord_bot.session import BattleSession

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# channel_id → BattleSession
_sessions: dict[int, BattleSession] = {}


BUFF_DICT, SKILL_DICT = load_spreadsheet_data()
intents = discord.Intents.default()
intents.message_content = True


_INTERACTION_TTL = 2.5  # Discord의 3초 제한에 여유를 둔 임계값


class XeteadBot(commands.Bot):
    async def setup_hook(self):
        self.tree.interaction_check = _check_interaction_age
        await self.tree.sync()


async def _check_interaction_age(interaction: discord.Interaction) -> bool:
    age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
    if age > _INTERACTION_TTL:
        logger.warning(
            "만료된 인터랙션 무시 (age=%.1fs, command=/%s) — 게이트웨이 재연결로 재전송된 이벤트",
            age,
            interaction.command.name if interaction.command else "unknown",
        )
        return False
    return True


bot = XeteadBot(command_prefix="!", intents=intents)
tree = bot.tree


@tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if (
        isinstance(error, app_commands.CommandInvokeError)
        and isinstance(error.original, discord.NotFound)
        and error.original.code == 10062
    ):
        age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
        cmd = interaction.command.name if interaction.command else "unknown"
        logger.warning(
            "인터랙션 만료 (age=%.1fs, command=/%s) — 세션 resume으로 재전송된 이벤트이거나 복수 인스턴스 실행 중",
            age,
            cmd,
        )
        return
    logger.error("앱 커맨드 오류: %s", error, exc_info=error)


@tree.command(name="전투", description="새 전투 세션을 시작합니다.")
async def cmd_전투(interaction: discord.Interaction):
    cid = interaction.channel_id
    if cid in _sessions:
        await interaction.response.send_message(
            "⚠️ 이미 진행 중인 세션이 있습니다. `/종료`로 먼저 종료하세요.",
            ephemeral=True,
        )
        return

    _sessions[cid] = BattleSession(BUFF_DICT, SKILL_DICT)

    await interaction.response.send_message(
        f"⚔️ **새 전투 세션이 생성되었습니다!**\n\n"
        f"{STAT_RULES}\n"
        f"**아군 추가**: `/캐릭터`\n"
        f"**적군 추가**: `/적군`"
    )


@tree.command(name="캐릭터", description="아군 캐릭터를 추가합니다.")
@app_commands.describe(
    이름="캐릭터 이름",
    공격력="공격력 (3~12)",
    체력="체력 (60~100)",
    사거리="사거리 (1~3)",
    공격속성="물리 또는 마법",
    마법저항="낮음, 보통, 높음",
    열="배치할 열 (1~7, 기본 1)",
)
async def cmd_캐릭터(
    interaction: discord.Interaction,
    이름: str,
    공격력: int,
    체력: int,
    사거리: int,
    공격속성: str,
    마법저항: str,
    열: int = 1,
):
    session = _sessions.get(interaction.channel_id)
    if not session:
        await interaction.response.send_message(
            "진행 중인 세션이 없습니다. `/전투`로 시작하세요.", ephemeral=True
        )
        return
    if session.started:
        await interaction.response.send_message(
            "전투가 이미 시작되었습니다.", ephemeral=True
        )
        return

    err = validate_stats(공격력, 체력, 사거리)
    if err:
        await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        return

    try:
        is_magic = parse_attack_type(공격속성)
        m_res = parse_m_res(마법저항)
        col = BattlefieldColumnIndex.from_str(str(열))
    except ValueError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return

    data = CharacterDataFromSpreadsheet(
        name=이름,
        mastodon_id="",
        curr_hp=체력,
        max_hp=체력,
        atk=공격력,
        attack_range=사거리,
        m_res=m_res,
        is_magic_attacker=is_magic,
        max_cost=3,
        passive_buff_id="",
        skill_1_id="",
        skill_2_id="",
        skill_3_id="",
    )

    try:
        session.add_character(data, FactionType.ALLY, col)  # touch() 내부 호출
    except CommandValidationError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return

    await interaction.response.send_message(
        f"✅ **{이름}** (아군)을 {열}열에 배치했습니다.\n"
        f"공격력 {공격력} / 체력 {체력} / 사거리 {사거리} / {'마법' if is_magic else '물리'} / 마법저항 {마법저항}\n\n"
        + SKILL_HELP
    )


@tree.command(name="적군", description="적군 캐릭터를 추가합니다.")
@app_commands.describe(
    이름="적군 이름",
    공격력="공격력",
    체력="체력",
    사거리="사거리 (1~3)",
    공격속성="물리 또는 마법",
    마법저항="낮음, 보통, 높음",
    열="배치할 열 (1~7, 기본 1)",
)
async def cmd_적군(
    interaction: discord.Interaction,
    이름: str,
    공격력: int,
    체력: int,
    사거리: int,
    공격속성: str,
    마법저항: str,
    열: int = 1,
):
    session = _sessions.get(interaction.channel_id)
    if not session:
        await interaction.response.send_message(
            "진행 중인 세션이 없습니다.", ephemeral=True
        )
        return
    if session.started:
        await interaction.response.send_message(
            "전투가 이미 시작되었습니다.", ephemeral=True
        )
        return

    try:
        is_magic = parse_attack_type(공격속성)
        m_res = parse_m_res(마법저항)
        col = BattlefieldColumnIndex.from_str(str(열))
    except ValueError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return

    data = CharacterDataFromSpreadsheet(
        name=이름,
        mastodon_id="",
        curr_hp=체력,
        max_hp=체력,
        atk=공격력,
        attack_range=사거리,
        m_res=m_res,
        is_magic_attacker=is_magic,
        max_cost=3,
        passive_buff_id="",
        skill_1_id="",
        skill_2_id="",
        skill_3_id="",
    )

    try:
        session.add_character(data, FactionType.ENEMY, col)  # touch() 내부 호출
    except CommandValidationError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return

    await interaction.response.send_message(
        f"✅ **{이름}** (적군)을 {열}열에 배치했습니다.\n"
        f"공격력 {공격력} / 체력 {체력} / 사거리 {사거리} / {'마법' if is_magic else '물리'} / 마법저항 {마법저항}\n\n"
        + SKILL_HELP
    )


@tree.command(name="스킬", description="캐릭터의 스킬을 지정합니다.")
@app_commands.describe(
    캐릭터이름="스킬을 지정할 캐릭터 이름",
    패시브="패시브 버프 ID (생략 가능)",
    스킬1="코스트 2 스킬 ID (생략 가능)",
    스킬2="코스트 3 스킬 ID (생략 가능)",
)
async def cmd_스킬(
    interaction: discord.Interaction,
    캐릭터이름: str,
    패시브: Optional[str] = None,
    스킬1: Optional[str] = None,
    스킬2: Optional[str] = None,
):
    session = _sessions.get(interaction.channel_id)
    if not session:
        await interaction.response.send_message(
            "진행 중인 세션이 없습니다.", ephemeral=True
        )
        return
    if session.started:
        await interaction.response.send_message(
            "전투가 이미 시작되었습니다.", ephemeral=True
        )
        return
    if not session.has_character(캐릭터이름):
        await interaction.response.send_message(
            f"❌ '{캐릭터이름}'을 찾을 수 없습니다.", ephemeral=True
        )
        return

    errors = []
    if 패시브 and 패시브 not in BUFF_DICT:
        errors.append(f"패시브 ID `{패시브}`를 찾을 수 없습니다.")
    if 스킬1 and 스킬1 not in SKILL_DICT:
        errors.append(f"스킬1 ID `{스킬1}`을 찾을 수 없습니다.")
    if 스킬2 and 스킬2 not in SKILL_DICT:
        errors.append(f"스킬2 ID `{스킬2}`를 찾을 수 없습니다.")
    if errors:
        await interaction.response.send_message(
            "❌ " + "\n".join(errors), ephemeral=True
        )
        return

    try:
        session.set_skills(캐릭터이름, 패시브, 스킬1, 스킬2)
    except CommandValidationError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return

    lines = [f"✅ **{캐릭터이름}**의 스킬이 설정되었습니다."]
    if 패시브:
        lines.append(f"- 패시브: `{패시브}`")
    if 스킬1:
        lines.append(f"- 스킬1 (코스트 2): `{스킬1}`")
    if 스킬2:
        lines.append(f"- 스킬2 (코스트 3): `{스킬2}`")
    if not (패시브 or 스킬1 or 스킬2):
        lines.append("(스킬 없음으로 설정)")

    await interaction.response.send_message("\n".join(lines))


@tree.command(name="스킬목록", description="사용 가능한 스킬 목록을 표시합니다.")
async def cmd_스킬목록(interaction: discord.Interaction):
    if not SKILL_DICT:
        await interaction.response.send_message(
            "등록된 스킬이 없습니다.", ephemeral=True
        )
        return
    lines = ["**스킬 목록**"]
    for sid, skill in SKILL_DICT.items():
        lines.append(f"- `{sid}` — 코스트 {skill.cost}")
    msg = "\n".join(lines)
    if len(msg) > 1900:
        msg = msg[:1900] + "\n...(생략)"
    await interaction.response.send_message(msg, ephemeral=True)


@tree.command(name="버프목록", description="사용 가능한 패시브 버프 목록을 표시합니다.")
async def cmd_버프목록(interaction: discord.Interaction):
    if not BUFF_DICT:
        await interaction.response.send_message(
            "등록된 버프가 없습니다.", ephemeral=True
        )
        return
    lines = ["**패시브 버프 목록**"]
    for bid in BUFF_DICT:
        lines.append(f"- `{bid}`")
    msg = "\n".join(lines)
    if len(msg) > 1900:
        msg = msg[:1900] + "\n...(생략)"
    await interaction.response.send_message(msg, ephemeral=True)


@tree.command(name="시작", description="전투를 시작합니다.")
async def cmd_시작(interaction: discord.Interaction):
    session = _sessions.get(interaction.channel_id)
    if not session:
        await interaction.response.send_message(
            "진행 중인 세션이 없습니다. `/전투`로 시작하세요.", ephemeral=True
        )
        return
    if session.started:
        await interaction.response.send_message("이미 시작되었습니다.", ephemeral=True)
        return
    if not session.context.characters:
        await interaction.response.send_message(
            "캐릭터를 최소 1명 이상 배치하세요.", ephemeral=True
        )
        return

    session.started = True
    session.touch()
    # ENEMY_PRE_ACTION 진입 → on_start_round 호출 (코스트 초기화 포함)
    session.manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )

    await interaction.response.send_message(
        f"⚔️ **전투 시작!**\n"
        f"현재 페이즈: {PHASE_NAMES[session.current_phase]}\n\n"
        f"```\n{session.context}\n```\n"
        f'행동: `/행동 이름:... 커맨드:"[커맨드]"`  |  페이즈 전환: `/페이즈`'
    )


@tree.command(name="행동", description="캐릭터의 행동을 선언합니다.")
@app_commands.describe(
    이름="행동할 캐릭터 이름",
    커맨드="커맨드 문자열 (예: [이동/1 - 공격/적군이름])",
)
async def cmd_행동(interaction: discord.Interaction, 이름: str, 커맨드: str):
    session = _sessions.get(interaction.channel_id)
    if not session:
        await interaction.response.send_message(
            "진행 중인 세션이 없습니다.", ephemeral=True
        )
        return
    if not session.started:
        await interaction.response.send_message(
            "전투가 시작되지 않았습니다. `/시작`을 입력하세요.", ephemeral=True
        )
        return

    char_id = CharacterId(이름)
    if char_id not in session.context.characters:
        await interaction.response.send_message(
            f"❌ '{이름}'을 찾을 수 없습니다.", ephemeral=True
        )
        return

    try:
        parsed = parse_character_command(char_id, 커맨드)
        if parsed is None:
            await interaction.response.send_message(
                "❌ 커맨드 형식이 올바르지 않습니다. `[커맨드]` 형태로 입력하세요.",
                ephemeral=True,
            )
            return
        session.manager.process_command(parsed)
        session.touch()
    except CommandValidationError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return
    except Exception as e:
        logger.exception("행동 처리 오류")
        await interaction.response.send_message(
            f"❌ 처리 중 예외 발생: {e}", ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"✅ **{이름}**의 행동이 처리되었습니다.\n```\n{session.context}\n```"
    )


@tree.command(name="페이즈", description="다음 라운드 페이즈로 전환합니다.")
async def cmd_페이즈(interaction: discord.Interaction):
    session = _sessions.get(interaction.channel_id)
    if not session:
        await interaction.response.send_message(
            "진행 중인 세션이 없습니다.", ephemeral=True
        )
        return
    if not session.started:
        await interaction.response.send_message(
            "전투가 시작되지 않았습니다.", ephemeral=True
        )
        return

    try:
        next_phase = session.advance_phase()
    except Exception as e:
        logger.exception("페이즈 전환 오류")
        await interaction.response.send_message(
            f"❌ 페이즈 전환 중 오류: {e}", ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"🔄 **페이즈 전환**: {PHASE_NAMES[next_phase]}\n```\n{session.context}\n```"
    )


@tree.command(name="현황", description="현재 전장 상황을 표시합니다.")
async def cmd_현황(interaction: discord.Interaction):
    session = _sessions.get(interaction.channel_id)
    if not session:
        await interaction.response.send_message(
            "진행 중인 세션이 없습니다.", ephemeral=True
        )
        return

    phase_str = (
        PHASE_NAMES[session.current_phase] if session.started else "전투 준비 중"
    )
    await interaction.response.send_message(
        f"**현재 페이즈**: {phase_str}\n```\n{session.context}\n```"
    )


@tree.command(name="종료", description="전투를 종료하고 세션을 삭제합니다.")
async def cmd_종료(interaction: discord.Interaction):
    cid = interaction.channel_id
    if cid not in _sessions:
        await interaction.response.send_message(
            "진행 중인 세션이 없습니다.", ephemeral=True
        )
        return

    _sessions.pop(cid)
    await interaction.response.send_message("🏁 전투 세션이 종료되었습니다.")


@tasks.loop(minutes=CLEANUP_INTERVAL_MINUTES)
async def cleanup_expired_sessions():
    """만료된 세션을 주기적으로 정리하고, 해당 채널에 안내 메시지를 전송한다."""
    expired = [cid for cid, s in _sessions.items() if s.is_expired()]
    for cid in expired:
        _sessions.pop(cid)
        try:
            channel = bot.get_channel(cid)
            if channel:
                await channel.send(
                    f"⏰ 장시간 활동이 없어 전투 세션이 자동 종료되었습니다. "
                    f"(`{SESSION_TIMEOUT_SECONDS // 3600}`시간 초과)"
                )
        except Exception:
            pass  # 채널 접근 실패는 무시
    if expired:
        logger.info(f"만료 세션 {len(expired)}개 정리 완료.")


@bot.event
async def on_ready():
    if not cleanup_expired_sessions.is_running():
        cleanup_expired_sessions.start()
    logger.info(f"봇 준비 완료: {bot.user} (ID: {bot.user.id})")


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_BOT_TOKEN"])
