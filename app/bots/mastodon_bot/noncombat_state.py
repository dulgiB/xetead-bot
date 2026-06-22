from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DailyQuestMidState:
    """[의뢰] 응답 후 플레이어의 판정 답글을 기다리는 중간 상태."""

    quest_id: str
    bot_reply_post_id: int  # 봇이 의뢰를 알려준 포스트 ID


@dataclass
class InvestigationQuestStatus:
    """상시조사 구간에서 특정 의뢰의 수주 상태."""

    quest_id: str
    overview_post_id: int  # 봇이 개요를 보낸 포스트 ID
    participants: list[str] = field(default_factory=list)  # [수락]한 acct 목록


@dataclass
class NonCombatState:
    # venue_name → quest_id 매핑 ([상시조사] 요청 시 스프레드시트에서 갱신)
    investigation_venue_to_quest: dict[str, str] = field(default_factory=dict)
    # venue_name → 이미 수주됐을 때 출력할 지문
    investigation_venue_to_desc: dict[str, str] = field(default_factory=dict)
    # acct → 봇이 보낸 조사 메뉴 게시물 ID
    investigation_menu_post_id: dict[str, int] = field(default_factory=dict)
    # acct → 봇이 보낸 의뢰 개요 게시물 ID
    investigation_overview_post_id: dict[str, int] = field(default_factory=dict)
    # acct → 이번 상시조사 구간에서 수락한 quest_id (1개 제한)
    investigation_accepted: dict[str, str] = field(default_factory=dict)
    # quest_id → InvestigationQuestStatus
    quest_status: dict[str, InvestigationQuestStatus] = field(default_factory=dict)
    # acct → 현재 개요를 보고 있는 quest_id (수락 시 역추적용)
    investigation_acct_to_quest_id: dict[str, str] = field(default_factory=dict)

    # 일일 의뢰 중간 상태 (acct → DailyQuestMidState)
    daily_quest_mid: dict[str, DailyQuestMidState] = field(default_factory=dict)

    def reset_investigation(self) -> None:
        """상시조사 종료 시 관련 상태를 초기화한다."""
        self.investigation_venue_to_quest.clear()
        self.investigation_venue_to_desc.clear()
        self.investigation_menu_post_id.clear()
        self.investigation_overview_post_id.clear()
        self.investigation_accepted.clear()
        self.quest_status.clear()
        self.investigation_acct_to_quest_id.clear()

    def get_daily_quest_post_ids(self) -> set[int]:
        return {s.bot_reply_post_id for s in self.daily_quest_mid.values()}

    def get_investigation_menu_post_ids(self) -> set[int]:
        return set(self.investigation_menu_post_id.values())

    def get_investigation_overview_post_ids(self) -> set[int]:
        return set(self.investigation_overview_post_id.values())

    def find_acct_by_investigation_menu_post(self, post_id: int) -> Optional[str]:
        for acct, pid in self.investigation_menu_post_id.items():
            if pid == post_id:
                return acct
        return None
