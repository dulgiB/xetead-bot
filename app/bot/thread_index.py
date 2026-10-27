"""봇이 본 게시물의 부모 관계로 스레드 조상을 거슬러 올라가는 색인.

답글이 어느 전투/세션 스레드에 속하는지는 그 조상에 세션 게시물이 있는지로
판정한다. Mastodon의 스레드 조회(`status_context`)는 스레드 전체를 돌려주므로
깊은 RP 스레드에서는 한 번에 20초가 넘게 걸린다. 세션 게시물은 보통 스레드
중간 어딘가에 있으므로, 거기까지만 부모를 하나씩 따라 올라가면 된다.

그 스레드의 게시물은 대부분 봇이 이미 봤다 — 자기가 올린 게시물과 처리한
멘션이다. 그 부모 관계를 모아 두면 대부분의 답글은 API 없이 조상을 따라 올라갈
수 있다. 부모 관계는 게시 후 바뀌지 않으므로 무효화가 필요 없다. 모르는
게시물에서 끊기면(사담에 단 답글, 재기동 직후) 호출측이 그 게시물 하나를
조회해 기록하고 다시 따라간다.

작성자도 함께 기록한다 — 일반 의뢰 [수락]이 그 스레드에 글을 쓴 인원을
참여자로 잡을 때 같은 경로로 API 없이 읽는다. 작성자도 게시 후 바뀌지 않는다.
"""

from collections import OrderedDict
from typing import Iterable, Optional

# 메모리 상한. 한 전투가 남기는 게시물 수에 비해 넉넉하다.
_MAX_ENTRIES = 20000


def _snowflake(status_id: int | str) -> Optional[int]:
    try:
        return int(status_id)
    except (TypeError, ValueError):
        return None


class ThreadIndex:
    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._parent_of: "OrderedDict[int, Optional[int]]" = OrderedDict()
        self._author_of: dict[int, str] = {}
        self._max_entries = max_entries

    def record(
        self,
        status_id: int,
        in_reply_to_id: Optional[int],
        author: Optional[str] = None,
    ) -> None:
        self._parent_of[status_id] = in_reply_to_id
        self._parent_of.move_to_end(status_id)
        if author is not None:
            self._author_of[status_id] = author
        while len(self._parent_of) > self._max_entries:
            evicted, _ = self._parent_of.popitem(last=False)
            self._author_of.pop(evicted, None)

    def author_of(self, status_id: int) -> Optional[str]:
        """기록된 작성자 acct. 작성자 없이 기록됐거나 모르는 게시물이면 None."""
        return self._author_of.get(status_id)

    def ancestor_ids(
        self, in_reply_to_id: int, wanted: Iterable[int]
    ) -> tuple[set[int], Optional[int]]:
        """`in_reply_to_id`부터 위로 올라간 조상 id들과, 끊긴 지점(모르는
        게시물 id, 끝까지 따라갔으면 None).

        `wanted` 중 하나를 만나면 거기서 멈춘다 — 아래에서부터 올라가므로
        처음 만난 것이 가장 가까운 조상이다. `wanted`의 어느 게시물보다
        오래된 게시물에 닿아도 멈춘다: 부모는 언제나 자식보다 먼저 게시되어
        id가 작으므로, 그 위에서는 `wanted`가 나올 수 없다. 이 판정 덕에
        세션과 무관한 깊은 스레드에서도 세션이 열린 뒤의 게시물만 따라간다."""
        targets = set(wanted)
        target_ids = [_snowflake(t) for t in targets]
        oldest = (
            min(t for t in target_ids if t is not None)
            if target_ids and None not in target_ids
            else None
        )
        ancestors: set[int] = set()
        current: Optional[int] = in_reply_to_id
        while current is not None:
            ancestors.add(current)
            if current in targets:
                break
            current_id = _snowflake(current)
            if oldest is not None and current_id is not None and current_id < oldest:
                break
            if current not in self._parent_of:
                return ancestors, current
            current = self._parent_of[current]
        return ancestors, None
