from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DailyQuestMidState:
    """[의뢰] 응답 후 플레이어의 판정 답글을 기다리는 중간 상태."""

    bot_reply_post_id: int  # 봇이 의뢰를 알려준 포스트 ID


@dataclass
class InvestigationSession:
    """[상시조사] 진행 중 상태 하나. "필드" 시트에 field_id로 upsert되어
    봇 재기동에도 살아남고, 사담이 섞여도 스레드 조상만 거슬러 올라가면
    다시 찾을 수 있다(main.py의 MastodonBotListener._resolve_investigation_session
    참고).

    world 계정이 태그되는 응답(자율 탐사/장소 미지정/수락/미수락)이 나가면
    ended=True가 되고, 그 뒤로는 같은 스레드에 어떤 답글이 와도 더 이상
    상시조사 컨텍스트로 인식되지 않는다.

    이미 여러 사람이 참여 중인 스레드에서 [상시조사]를 보내면 그 인원 전원이
    accts에 들어가고, 그중 누가 답글을 보내든 같은 세션으로 이어진다.
    """

    field_id: str  # "필드" 시트 upsert 키. str(menu_post_id)로 고정.
    accts: list[str]  # 맨 앞이 [상시조사]를 보낸 계정.
    menu_post_id: int
    overview_post_id: Optional[int] = None
    quest_id: Optional[str] = None
    ended: bool = False


@dataclass
class NonCombatState:
    # field_id → 세션. 한 acct가 여러 세션에 동시에 참여할 수 있다 — 겹치면
    # 안 되는 것은 의뢰 수주(taken_by)뿐이고, 그건 [수락]이 따로 확인한다.
    investigations: dict[str, InvestigationSession] = field(default_factory=dict)

    daily_quest_mid: dict[str, DailyQuestMidState] = field(default_factory=dict)

    def get_daily_quest_post_ids(self) -> set[int]:
        return {s.bot_reply_post_id for s in self.daily_quest_mid.values()}

    def active_investigations(self, acct: str) -> list[InvestigationSession]:
        return [
            session
            for session in self.investigations.values()
            if not session.ended and acct in session.accts
        ]
