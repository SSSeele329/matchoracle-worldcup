import json

from scripts.run_demo_worker import run_demo_worker


def test_demo_worker_exits_after_empty_queue():
    events = []

    def request_fn(base_url, worker_id, token=None, timeout=10):
        return 200, {"job": None, "reason": "NO_RUNNABLE_JOB_OR_CONCURRENCY_LIMIT"}

    exit_code = run_demo_worker(
        "http://127.0.0.1:5012",
        "unit-worker",
        max_jobs=3,
        emit=events.append,
        request_fn=request_fn,
    )

    assert exit_code == 0
    assert json.loads(events[0])["event"] == "NO_RUNNABLE_JOB"
    assert json.loads(events[-1])["processedJobs"] == 0


def test_demo_worker_reports_failed_job_with_nonzero_exit():
    events = []
    calls = []

    def request_fn(base_url, worker_id, token=None, timeout=10):
        calls.append((base_url, worker_id, token, timeout))
        return 409, {
            "job": {
                "jobId": "job-1",
                "jobType": "ODDS_IMPORT",
                "status": "FAILED",
                "error": {"code": "ODDS_CSV_IMPORT_REJECTED"},
            }
        }

    exit_code = run_demo_worker(
        "http://localhost:5012",
        "unit-worker",
        token="secret",
        max_jobs=1,
        timeout=3,
        emit=events.append,
        request_fn=request_fn,
    )

    result_event = json.loads(events[0])
    summary = json.loads(events[-1])
    assert exit_code == 2
    assert calls == [("http://localhost:5012", "unit-worker", "secret", 3)]
    assert result_event["status"] == "FAILED"
    assert result_event["error"]["code"] == "ODDS_CSV_IMPORT_REJECTED"
    assert summary["failedJobs"] == 1


def test_demo_worker_reports_transport_failure_without_traceback():
    events = []

    def request_fn(base_url, worker_id, token=None, timeout=10):
        return 0, {"error": {"code": "DEMO_WORKER_REQUEST_FAILED", "message": "connection refused"}}

    exit_code = run_demo_worker(
        "http://127.0.0.1:5012",
        "unit-worker",
        emit=events.append,
        request_fn=request_fn,
    )

    assert exit_code == 2
    assert json.loads(events[0])["event"] == "WORKER_REQUEST_FAILED"
    assert json.loads(events[0])["error"]["code"] == "DEMO_WORKER_REQUEST_FAILED"
    assert json.loads(events[-1])["failedJobs"] == 1
