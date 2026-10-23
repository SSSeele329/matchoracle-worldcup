#!/usr/bin/env python3
"""Run a bounded number of MatchOracle background jobs for local demos.

This is intentionally not a daemon. It exits after a fixed number of attempts or
when the queue is empty, so production deployments still need a real worker
runtime chosen for the hosting platform.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "http://127.0.0.1:5012"


def post_run_next(base_url, worker_id, token=None, timeout=10):
    headers = {
        "Content-Type": "application/json",
        "X-MatchOracle-Worker-Id": worker_id,
    }
    if token:
        headers["X-MatchOracle-Worker-Token"] = token
    else:
        headers["X-MatchOracle-Worker"] = "1"
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/jobs/run-next",
        data=b"{}",
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"error": body}
        return error.code, payload
    except urllib.error.URLError as error:
        return 0, {
            "error": {
                "code": "DEMO_WORKER_REQUEST_FAILED",
                "message": str(error.reason),
            }
        }


def run_demo_worker(base_url, worker_id, token=None, max_jobs=1, timeout=10, emit=print, request_fn=post_run_next):
    processed = 0
    failed = 0
    empty = False
    for _ in range(max(1, int(max_jobs))):
        status, payload = request_fn(base_url, worker_id, token=token, timeout=timeout)
        if (payload or {}).get("error") and not (payload or {}).get("job"):
            failed += 1
            emit(json.dumps({
                "event": "WORKER_REQUEST_FAILED",
                "httpStatus": status,
                "error": payload.get("error"),
            }, ensure_ascii=False))
            break
        job = (payload or {}).get("job")
        if not job:
            empty = True
            emit(json.dumps({
                "event": "NO_RUNNABLE_JOB",
                "httpStatus": status,
                "reason": (payload or {}).get("reason"),
            }, ensure_ascii=False))
            break
        processed += 1
        if status >= 400 or job.get("status") == "FAILED":
            failed += 1
        emit(json.dumps({
            "event": "JOB_RESULT",
            "httpStatus": status,
            "jobId": job.get("jobId"),
            "jobType": job.get("jobType"),
            "status": job.get("status"),
            "error": job.get("error"),
        }, ensure_ascii=False))
        if job.get("status") not in {"SUCCEEDED", "FAILED"}:
            break
    summary = {
        "event": "DEMO_WORKER_SUMMARY",
        "processedJobs": processed,
        "failedJobs": failed,
        "queueEmpty": empty,
    }
    emit(json.dumps(summary, ensure_ascii=False))
    return 2 if failed else 0


def build_parser():
    parser = argparse.ArgumentParser(description="Run a bounded local MatchOracle demo worker.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local app base URL.")
    parser.add_argument("--worker-id", default="demo-worker", help="Worker id sent to the app.")
    parser.add_argument("--token", default=None, help="Optional MATCHORACLE_WORKER_TOKEN value.")
    parser.add_argument("--max-jobs", type=int, default=1, help="Maximum jobs to run before exiting.")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP timeout in seconds.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_demo_worker(
        args.base_url,
        args.worker_id,
        token=args.token,
        max_jobs=args.max_jobs,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
