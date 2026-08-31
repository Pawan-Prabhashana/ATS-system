"""The in-process progress registry backing background pull/rescore."""
from app.pipeline import progress


def test_try_start_guards_duplicate_runs():
    key = "test-key-1"
    assert progress.try_start(key, "ingest", total=10) is True
    # A second start while running is refused (no duplicate job).
    assert progress.try_start(key, "ingest") is False
    snap = progress.snapshot(key)
    assert snap["status"] == "running" and snap["total"] == 10 and snap["processed"] == 0


def test_report_and_finish():
    key = "test-key-2"
    progress.try_start(key, "rescore", total=3)
    progress.report(key, 2, total=3)
    snap = progress.snapshot(key)
    assert snap["processed"] == 2 and snap["total"] == 3
    progress.finish(key, summary={"rescored": 3})
    snap = progress.snapshot(key)
    assert snap["status"] == "done" and snap["summary"] == {"rescored": 3}
    # Finished -> a new run may start again.
    assert progress.try_start(key, "rescore") is True


def test_finish_with_error():
    key = "test-key-3"
    progress.try_start(key, "ingest")
    progress.finish(key, error="boom")
    snap = progress.snapshot(key)
    assert snap["status"] == "error" and snap["error"] == "boom"


def test_snapshot_missing_key_is_none():
    assert progress.snapshot("never-started") is None
