from dataclasses import dataclass, field

from bot.session import BattleSession


@dataclass
class DmBattleState:
    """DM(다이렉트 메시지) 전투 세션 상태.

    본 전투와 동일한 BattleSession(풀스탯 BattlefieldContext, 4페이즈 라운드
    엔진)을 그대로 쓰되, 대련/상시전투처럼 하나의 스레드 안에서 답글로 이어지며
    본 전투와 달리 여러 개가 동시에 진행될 수 있다(BotState.dm_battles에 키가
    active_post_id인 dict로 관리).
    """

    session: BattleSession

    # "필드"/"로그_전투" 시트용 안정적 id. [전투 발생] 응답 게시물의 status_id로
    # 최초 1회 고정되며, active_post_id처럼 매 페이즈 바뀌지 않는다.
    field_id: str

    # 현재 스레드 tip 게시물 id. 답글 매칭 및 다음 페이즈 게시물의
    # in_reply_to_id로 쓰이며, 페이즈 전환마다 갱신된다.
    active_post_id: int

    # 최초 [전투 발생] DM의 visibility. 세션 내내 고정해, 봇이 새로 올리는
    # 페이즈 전환 게시물이 이 값을 그대로 따르게 한다. 개별 캐릭터 커맨드
    # 답글은 원본 메시지의 visibility를 그대로 따르므로 이 필드가 필요 없다.
    visibility: str = "direct"

    # 이 DM 전투에 실제 계정으로 참여 중인 캐릭터의 mastodon acct 목록.
    # visibility가 "direct"인 스레드는 각 게시물 자체에 명시적으로 멘션된
    # 계정만 볼 수 있으므로, 페이즈 전환/정산/종료 게시물에도 매번 이
    # 목록을 멘션으로 붙여야 참가자가 스레드를 계속 볼 수 있다.
    mentions: list[str] = field(default_factory=list)
