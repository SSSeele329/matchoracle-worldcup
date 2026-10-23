import json

from scripts.run_production_worker import build_worker_config, run_worker_loop


def test_production_worker_requires_token_by_default():
    events = []
    exit_code = run_worker_loop({
        "base_url": "http://web:5012",
        "worker_id": "unit-worker",
        "token": "",
        "sleep_seconds": 0,
        "request_timeout": 1,
        "max_iterations": 1,
        "require_token": True,
    }, emit=events.append)

    payload = json.loads(events[0])
    assert exit_code == 2
    assert payload["event"] == "PRODUCTION_WORKER_CONFIG_ERROR"
    assert payload["code"] == "MISSING_WORKER_TOKEN"


def test_production_worker_runs_one_authenticated_iteration():
    events = []
    calls = []

    def request_fn(base_url, worker_id, token=None, timeout=20):
        calls.append((base_url, worker_id, token, timeout))
        return 200, {
            "job": {
                "jobId": "job-1",
                "jobType": "T60_LINEUP_RECALC",
                "status": "SUCCEEDED",
            }
        }

    exit_code = run_worker_loop({
        "base_url": "http://web:5012",
        "worker_id": "unit-worker",
        "token": "worker-token",
        "sleep_seconds": 0,
        "request_timeout": 7,
        "max_iterations": 1,
        "require_token": True,
    }, emit=events.append, sleep_fn=lambda _seconds: None, request_fn=request_fn)

    payloads = [json.loads(event) for event in events]
    assert exit_code == 0
    assert calls == [("http://web:5012", "unit-worker", "worker-token", 7)]
    assert payloads[0]["event"] == "PRODUCTION_WORKER_STARTED"
    assert payloads[1]["event"] == "PRODUCTION_WORKER_JOB_RESULT"
    assert payloads[1]["status"] == "SUCCEEDED"
    assert payloads[-1]["processedJobs"] == 1


def test_production_worker_idle_once_exits_cleanly():
    events = []

    def request_fn(base_url, worker_id, token=None, timeout=20):
        return 200, {"job": None, "reason": "NO_RUNNABLE_JOB_OR_CONCURRENCY_LIMIT"}

    exit_code = run_worker_loop({
        "base_url": "http://web:5012",
        "worker_id": "unit-worker",
        "token": "worker-token",
        "sleep_seconds": 0,
        "request_timeout": 7,
        "max_iterations": 1,
        "require_token": True,
    }, emit=events.append, sleep_fn=lambda _seconds: None, request_fn=request_fn)

    payloads = [json.loads(event) for event in events]
    assert exit_code == 0
    assert payloads[1]["event"] == "PRODUCTION_WORKER_IDLE"
    assert payloads[-1]["processedJobs"] == 0


def test_production_worker_treats_http_error_without_job_as_failure():
    events = []

    def request_fn(base_url, worker_id, token=None, timeout=20):
        return 503, {"reason": "upstream unavailable"}

    exit_code = run_worker_loop({
        "base_url": "http://web:5012",
        "worker_id": "unit-worker",
        "token": "worker-token",
        "sleep_seconds": 0,
        "request_timeout": 7,
        "max_iterations": 1,
        "require_token": True,
    }, emit=events.append, sleep_fn=lambda _seconds: None, request_fn=request_fn)

    payloads = [json.loads(event) for event in events]
    assert exit_code == 2
    assert payloads[1]["event"] == "PRODUCTION_WORKER_REQUEST_FAILED"
    assert payloads[1]["httpStatus"] == 503
    assert payloads[-1]["failedJobs"] == 1


def test_production_worker_config_uses_environment(monkeypatch):
    monkeypatch.setenv("MATCHORACLE_APP_BASE_URL", "http://web:5012")
    monkeypatch.setenv("MATCHORACLE_WORKER_ID", "env-worker")
    monkeypatch.setenv("MATCHORACLE_WORKER_TOKEN", "env-token")
    monkeypatch.setenv("MATCHORACLE_WORKER_SLEEP_SECONDS", "3")
    monkeypatch.setenv("MATCHORACLE_WORKER_REQUEST_TIMEOUT_SECONDS", "9")

    class Args:
        base_url = None
        worker_id = None
        token = None
        sleep_seconds = None
        timeout = None
        max_iterations = None
        once = True
        allow_missing_token_for_local_dev = False

    config = build_worker_config(Args())

    assert config["base_url"] == "http://web:5012"
    assert config["worker_id"] == "env-worker"
    assert config["token"] == "env-token"
    assert config["sleep_seconds"] == 3
    assert config["request_timeout"] == 9
    assert config["max_iterations"] == 1
