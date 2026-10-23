"""체력이 시트에 기록될 때 그 캐릭터 계정의 자기소개 체력 표기도 맞춰 주는
백그라운드 동기화기.

자기소개 본문을 고치는 일은 마스토돈 포크의 관리자 API
(`PUT /api/v1/admin/accounts/:id/bio_hp`)가 한다. 본문에서 "현재/최대" 표기를
찾는 규칙도 서버 쪽에 있어서, 봇은 계정과 체력 두 값만 넘긴다 — 표기가 없거나
애매하면 서버가 아무것도 바꾸지 않는다.

- **답글을 기다리게 하지 않는다.** 자기소개는 답글 내용과 무관하므로 호출은
  전용 스레드 하나가 한다. 같은 계정에 밀린 요청은 마지막 값 하나로 합친다 —
  광역기 한 방에 여러 번 맞아도 최종 체력만 쓰면 된다.
- **실패는 로그만 남긴다.** 다음 체력 변동 때 다시 맞춰진다.
- `MASTODON_ADMIN_ACCESS_TOKEN`이 없으면 `install()`하지 않고, 그때
  `notify()`는 아무것도 하지 않는다.
"""

import logging
import threading
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 10


class BioHpSyncer:
    def __init__(
        self,
        api_base_url: str,
        access_token: str,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._base_url = api_base_url.rstrip("/")
        self._session = session or requests.Session()
        self._session.headers["Authorization"] = f"Bearer {access_token}"
        self._account_ids: dict[str, str] = {}
        # acct → (현재 체력, 최대 체력). 같은 acct는 마지막 값만 남는다.
        self._pending: dict[str, tuple[int, int]] = {}
        self._cond = threading.Condition()
        self._busy = False
        self._thread = threading.Thread(
            target=self._run, name="bio-hp-sync", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def notify(self, acct: str, curr_hp: int, max_hp: int) -> None:
        with self._cond:
            self._pending[acct] = (curr_hp, max_hp)
            self._cond.notify()

    def wait_idle(self, timeout: Optional[float] = None) -> bool:
        with self._cond:
            return self._cond.wait_for(
                lambda: not self._pending and not self._busy, timeout=timeout
            )

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: bool(self._pending))
                acct, (curr_hp, max_hp) = self._pending.popitem()
                self._busy = True
            try:
                self.sync(acct, curr_hp, max_hp)
            except Exception:
                logger.exception("'%s' 자기소개 체력 갱신 실패", acct)
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def sync(self, acct: str, curr_hp: int, max_hp: int) -> str:
        """자기소개 체력을 갱신하고 서버가 알려준 결과(`updated`/`unchanged`/
        `not_found`/`ambiguous`/`invalid`)를 돌려준다."""
        account_id = self._account_id(acct)
        response = self._session.put(
            f"{self._base_url}/api/v1/admin/accounts/{account_id}/bio_hp",
            data={"current_hp": curr_hp, "max_hp": max_hp},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        result = response.json().get("result", "")
        if result not in ("updated", "unchanged"):
            logger.info("'%s' 자기소개 체력 미갱신: %s", acct, result)
        return result

    def _account_id(self, acct: str) -> str:
        account_id = self._account_ids.get(acct)
        if account_id is None:
            response = self._session.get(
                f"{self._base_url}/api/v1/accounts/lookup",
                params={"acct": acct},
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            account_id = self._account_ids[acct] = str(response.json()["id"])
        return account_id


_syncer: Optional[BioHpSyncer] = None


def install(syncer: BioHpSyncer) -> None:
    global _syncer
    _syncer = syncer
    syncer.start()


def notify(acct: str, curr_hp: int, max_hp: Optional[int]) -> None:
    """체력이 시트에 기록된 뒤 부른다. 계정이나 최대 체력을 모르면 넘어간다."""
    if _syncer is None or not acct or max_hp is None:
        return
    _syncer.notify(acct, curr_hp, max_hp)
