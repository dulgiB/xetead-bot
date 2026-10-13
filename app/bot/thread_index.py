"""봇이 본 게시물의 부모 관계로 스레드 조상을 API 없이 거슬러 올라가는 색인.

답글이 어느 전투/세션 스레드에 속하는지는 그 조상에 세션 게시물이 있는지로
판정한다. Mastodon의 스레드 조회(`status_context`)는 스레드가 깊어질수록
느려져(조상 40여 개에서 2~3초) 커맨드마다 부르기엔 비싸다. 대련처럼 서로의
답글에 이어 다는 스레드는 거의 모든 커맨드가 이 조회를 탄다.

그런데 그 스레드의 게시물은 대부분 봇이 이미 봤다 — 자기가 올린 게시물과
처리한 멘션이다. 그 부모 관계를 모아 두면 대부분의 답글은 조상을 직접 따라
올라갈 수 있다. 부모 관계는 게시 후 바뀌지 않으므로 무효화가 필요 없다.
모르는 게시물에서 끊기면(사담에 단 답글, 재기동 직후) 호출측이 API로
조회하고, 그 결과도 여기 기록해 다음부터는 쓰지 않게 한다.
"""

from collections import OrderedDict
from typing import Iterable, Optional

# 메모리 상한. 한 전투가 남기는 게시물 수에 비해 넉넉하다.
_MAX_ENTRIES = 20000


class ThreadIndex:
    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._parent_of: "OrderedDict[int, Optional[int]]" = OrderedDict()
        self._max_entries = max_entries

    def record(self, status_id: int, in_reply_to_id: Optional[int]) -> None:
        self._parent_of[status_id] = in_reply_to_id
        self._parent_of.move_to_end(status_id)
        while len(self._parent_of) > self._max_entries:
            self._parent_of.popitem(last=False)

    def record_ancestors(self, ancestors: Iterable[dict]) -> None:
        for ancestor in ancestors:
            self.record(ancestor["id"], ancestor.get("in_reply_to_id"))

    def ancestor_ids(
        self, in_reply_to_id: int, wanted: Iterable[int]
    ) -> Optional[set[int]]:
        """`in_reply_to_id`부터 위로 올라간 조상 id들. `wanted` 중 하나를
        만나면 거기서 멈춘다 — 아래에서부터 올라가므로 처음 만난 것이 가장
        가까운 조상이다. 루트까지 다 알면 전체 조상이다. 모르는 게시물에서
        끊기면 None이다."""
        targets = set(wanted)
        ancestors: set[int] = set()
        current: Optional[int] = in_reply_to_id
        while current is not None:
            ancestors.add(current)
            if current in targets:
                return ancestors
            if current not in self._parent_of:
                return None
            current = self._parent_of[current]
        return ancestors
