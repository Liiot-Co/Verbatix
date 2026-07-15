"""Verifies the in-process scheduler bounds concurrency and processes each
round independently, without hitting a real DB or the LLM.
"""
import threading
import time
from unittest.mock import patch

from app.core import scheduler


def test_scheduler_bounds_concurrency_across_rounds():
    max_workers = 2
    active = 0
    peak = 0
    lock = threading.Lock()
    done = threading.Event()
    processed = []

    def fake_run_round(round_id):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        processed.append(round_id)
        with lock:
            active -= 1
        if len(processed) == 5:
            done.set()

    with patch.object(scheduler.settings, "round_parallel_workers", max_workers), \
         patch.object(scheduler, "_run_round", side_effect=fake_run_round):
        scheduler.start()
        try:
            for i in range(5):
                scheduler.submit(i)
            assert done.wait(timeout=5)
        finally:
            scheduler.stop()

    assert peak <= max_workers
    assert sorted(processed) == list(range(5))


def test_run_round_marks_round_failed_on_exception():
    """process_round raising is caught and the round/run are flipped to 'failed'
    instead of leaving the worker crashed and the round stuck 'running' forever."""
    calls = []

    class FakeSession:
        def rollback(self):
            calls.append("rollback")

        def close(self):
            calls.append("close")

    fake_db = FakeSession()

    with patch.object(scheduler, "SessionLocal", return_value=fake_db), \
         patch("app.pipeline.process_round", side_effect=RuntimeError("boom")), \
         patch.object(scheduler, "_mark_round_failed") as mark_failed:
        scheduler._run_round("round-1")

    assert "rollback" in calls
    assert "close" in calls
    mark_failed.assert_called_once()
    assert mark_failed.call_args[0][1] == "round-1"
