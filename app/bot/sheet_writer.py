"""답글에 필요 없는 시트 기록을 알림 워커 밖에서 처리하는 백그라운드 기록기.

알림은 워커 하나가 순서대로 처리하므로, 커맨드 하나가 답글을 올린 뒤에도
로그·필드 행 기록이 끝날 때까지 다음 커맨드가 기다린다. 여럿이 한꺼번에
선언하면 이 대기가 줄줄이 쌓인다. 답글 내용과 무관한 기록(공개 필드 시트
렌더링, "로그_전투" 추가, 필드 DB 행 갱신)은 여기에 맡기고 워커는 다음
알림으로 넘어간다.

- **작업은 실행 시점에 라이브 상태를 읽으면 안 된다.** 워커가 그 사이 다음
  커맨드로 전장을 바꾸므로, 기록할 값은 넘기기 전에 워커 스레드에서 다
  만들어 둔다.
- **같은 시트를 다루는 함수는 입구에서 `wait_idle()`을 부른다.** 그 시트를
  워커가 직접 읽거나 쓰기 전에 밀린 작업을 끝내야 순서가 뒤집히지 않는다
  (예: 늦게 도착한 렌더링이 페이즈 전환 렌더링을 덮어쓰거나, 행 삽입으로
  밀린 필드 DB 행을 엉뚱한 번호로 갱신하는 것). 호출부가 아니라 함수
  입구에 두는 이유는 호출부가 수십 곳이라 하나만 빠뜨려도 조용히 꼬이기
  때문이다.
- **작업이 쓸 시트의 워커 쪽 캐시는 넘길 때 무효화한다.** 그러면 워커가
  그 시트를 다시 읽을 때 `wait_idle()` 뒤에 새로 읽게 된다.

기록기를 `install()`하지 않으면 `submit()`이 그 자리에서 바로 실행한다
(테스트와 같은 동기 동작). 작업은 하나의 스레드가 넣은 순서대로 처리한다.
프로세스가 내려갈 때 남은 작업은 버려진다 — 그 사이 재기동 복원은 직전
커맨드 하나만큼 낡은 필드 DB 행에서 시작할 수 있다.
"""

import logging
import queue
import threading
from typing import Callable, Optional

import gspread

from bot.sheet_cache import SheetCache

logger = logging.getLogger(__name__)

Job = Callable[[], None]


class SheetWriter:
    def __init__(self) -> None:
        self._queue: "queue.Queue[Job]" = queue.Queue()
        # 기록기 스레드 전용. 워커 스레드의 캐시와 공유하면 서로 값을 지운다.
        self._caches: dict[str, SheetCache] = {}
        self._thread = threading.Thread(
            target=self._run, name="sheet-writer", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def is_writer_thread(self) -> bool:
        return threading.current_thread() is self._thread

    def submit(self, job: Job) -> None:
        self._queue.put(job)

    def wait_idle(self) -> None:
        if not self.is_writer_thread():
            self._queue.join()

    def cache_for(self, spreadsheet: gspread.Spreadsheet) -> SheetCache:
        cache = self._caches.get(spreadsheet.id)
        if cache is None:
            cache = self._caches[spreadsheet.id] = SheetCache(spreadsheet)
        return cache

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                for cache in self._caches.values():
                    cache.reset_values()
                job()
            except Exception:
                logger.exception("백그라운드 시트 기록 실패")
            finally:
                self._queue.task_done()


_writer: Optional[SheetWriter] = None


def install(writer: SheetWriter) -> None:
    global _writer
    _writer = writer
    writer.start()


def submit(job: Job) -> None:
    if _writer is None:
        job()
        return
    _writer.submit(job)


def wait_idle() -> None:
    if _writer is not None:
        _writer.wait_idle()


def job_cache(
    spreadsheet: gspread.Spreadsheet, default: Optional[SheetCache]
) -> Optional[SheetCache]:
    """작업 안에서 쓸 캐시. 기록기 스레드에서는 그 스레드 전용 캐시를,
    동기 실행이면 호출측이 넘긴 워커 쪽 캐시를 돌려준다."""
    if _writer is not None and _writer.is_writer_thread():
        return _writer.cache_for(spreadsheet)
    return default
