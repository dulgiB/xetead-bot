import threading

import pytest

from bot import sheet_writer
from bot.field_sheet_renderer import render_public_field_sheet


@pytest.fixture
def writer():
    installed = sheet_writer.SheetWriter()
    sheet_writer.install(installed)
    yield installed
    installed.wait_idle()
    sheet_writer._writer = None


def test_submit_runs_inline_without_installed_writer():
    calls = []
    sheet_writer.submit(lambda: calls.append(threading.current_thread()))
    assert calls == [threading.current_thread()]


def test_jobs_run_in_submission_order_on_writer_thread(writer):
    """먼저 처리된 커맨드의 기록이 나중 커맨드의 기록을 덮어쓰지 않는다."""
    gate = threading.Event()
    order: list[str] = []

    def slow_first() -> None:
        gate.wait(timeout=5)
        order.append("A")

    sheet_writer.submit(slow_first)
    sheet_writer.submit(lambda: order.append("B"))
    gate.set()
    sheet_writer.wait_idle()

    assert order == ["A", "B"]


def test_wait_idle_blocks_until_pending_jobs_finish(writer):
    gate = threading.Event()
    done: list[bool] = []

    def job() -> None:
        gate.wait(timeout=5)
        done.append(True)

    sheet_writer.submit(job)
    threading.Timer(0.05, gate.set).start()
    sheet_writer.wait_idle()

    assert done == [True]


def test_wait_idle_inside_job_does_not_deadlock(writer):
    """기록기 스레드에서 같은 시트 함수(대기 지점 포함)를 불러도 멈추지 않는다."""
    done: list[bool] = []
    sheet_writer.submit(lambda: (sheet_writer.wait_idle(), done.append(True)))
    sheet_writer.wait_idle()
    assert done == [True]


def test_failed_job_does_not_stop_later_jobs(writer):
    done: list[bool] = []

    def boom() -> None:
        raise RuntimeError("시트 오류")

    sheet_writer.submit(boom)
    sheet_writer.submit(lambda: done.append(True))
    sheet_writer.wait_idle()

    assert done == [True]


class _RecordingSpreadsheet:
    id = "field-spreadsheet"

    def __init__(self) -> None:
        self.batches: list[str] = []
        self.gate = threading.Event()

    def batch_update(self, body: dict) -> None:
        tag = body["requests"]
        if tag == "background":
            self.gate.wait(timeout=5)
        self.batches.append(tag)


def test_direct_render_waits_for_background_render(writer, monkeypatch):
    """백그라운드 렌더링이 늦게 끝나도 그 뒤에 직접 한 렌더링(페이즈 전환
    등)을 덮어쓰지 않는다."""
    spreadsheet = _RecordingSpreadsheet()
    monkeypatch.setattr(
        "bot.field_sheet_renderer._field_worksheet", lambda spreadsheet, cache: None
    )
    monkeypatch.setattr(
        "bot.field_sheet_renderer._build_render_requests",
        lambda *args, **kwargs: "direct",
    )

    sheet_writer.submit(lambda: spreadsheet.batch_update({"requests": "background"}))
    threading.Timer(0.05, spreadsheet.gate.set).start()
    render_public_field_sheet(spreadsheet, None, 1, "아군 행동", {})  # type: ignore[arg-type]

    assert spreadsheet.batches == ["background", "direct"]


def test_job_cache_uses_writer_own_cache_on_writer_thread(writer):
    spreadsheet = _RecordingSpreadsheet()
    main_cache = object()
    seen = []

    sheet_writer.submit(
        lambda: seen.append(sheet_writer.job_cache(spreadsheet, main_cache))  # type: ignore[arg-type]
    )
    sheet_writer.wait_idle()

    assert seen[0] is not main_cache
    assert seen[0] is writer.cache_for(spreadsheet)  # type: ignore[arg-type]
    assert sheet_writer.job_cache(spreadsheet, main_cache) is main_cache  # type: ignore[arg-type]
