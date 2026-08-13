from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DailyQuestMidState:
    """[의뢰] 응답 후 플레이어의 판정 답글을 기다리는 중간 상태."""

    bot_reply_post_id: int  # 봇이 의뢰를 알려준 포스트 ID


@dataclass
class NonCombatState:
    # acct → 봇이 보낸 조사 메뉴 게시물 ID
    investigation_menu_post_id: dict[str, int] = field(default_factory=dict)
    # acct → 방금 확인한 의뢰 개요의 quest_id (finalize 시 아래
    # investigation_overview_quest로 옮겨지는 임시 다리 역할)
    investigation_acct_to_quest_id: dict[str, str] = field(default_factory=dict)
    # 봇이 보낸 의뢰 개요 게시물 ID → quest_id ([수락] 답글의 대상 의뢰 판별용)
    investigation_overview_quest: dict[int, str] = field(default_factory=dict)

    # 일일 의뢰 중간 상태 (acct → DailyQuestMidState)
    daily_quest_mid: dict[str, DailyQuestMidState] = field(default_factory=dict)

    def reset_investigation(self) -> None:
        """상시조사 종료 시 관련 상태를 초기화한다."""
        self.investigation_menu_post_id.clear()
        self.investigation_acct_to_quest_id.clear()
        self.investigation_overview_quest.clear()

    def get_daily_quest_post_ids(self) -> set[int]:
        return {s.bot_reply_post_id for s in self.daily_quest_mid.values()}

    def get_investigation_menu_post_ids(self) -> set[int]:
        return set(self.investigation_menu_post_id.values())

    def get_investigation_overview_post_ids(self) -> set[int]:
        return set(self.investigation_overview_quest.keys())

    def find_acct_by_investigation_menu_post(self, post_id: int) -> Optional[str]:
        for acct, pid in self.investigation_menu_post_id.items():
            if pid == post_id:
                return acct
        return None
