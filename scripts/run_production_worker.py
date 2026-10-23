#!/usr/bin/env python3
"""Run the MatchOracle background worker loop for deployable environments.

This worker is provider-agnostic. It only calls the app's authenticated
`/api/jobs/run-next` endpoint, so the same process can run on a VPS, container
sidecar, hosted worker, or scheduled platform worker.
"""

import argparse
import json
import os
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.run_demo_worker import DEFAULT_BASE_URL, post_run_next


DEFAULT_WORKER_ID = "matchoracle-worker"


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def build_worker_config(args):
    base_url = args.base_url or os.environ.get("MATCHORACLE_APP_BASE_URL") or DEFAULT_BASE_URL
    worker_id = args.worker_id or os.environ.get("MATCHORACLE_WORKER_ID") or DEFAULT_WORKER_ID
    token = args.token if args.token is not None else os.environ.get("MATCHORACLE_WORKER_TOKEN")
    sleep_seconds = args.sleep_seconds if args.sleep_seconds is not None else env_float("MATCHORACLE_WORKER_SLEEP_SECONDS", 5)
    request_timeout = args.timeout if args.timeout is not None else env_int("MATCHORACLE_WORKER_REQUEST_TIMEOUT_SECONDS", 20)
    max_iterations = args.max_iterations
    if args.once and max_iterations is None:
        max_iterations = 1
    return {
        "base_url": base_url,
        "worker_id": worker_id,
        "token": token,
        "sleep_seconds": max(0, float(sleep_seconds)),
        "request_timeout": max(1, int(request_timeout)),
        "max_iterations": max_iterations,
        "require_token": not args.allow_missing_token_for_local_dev,
    }


def event_payload(event, **fields):
    payload = {"event": event}
    payload.update(fields)
    return payload


def emit_json(payload, emit=print):
    emit(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def run_worker_loop(config, emit=print, sleep_fn=time.sleep, request_fn=post_run_next):
    if config.get("require_token") and not config.get("token"):
        emit_json(event_payload(
            "PRODUCTION_WORKER_CONFIG_ERROR",
            code="MISSING_WORKER_TOKEN",
            message="MATCHORACLE_WORKER_TOKEN is required for the production worker.",
        ), emit=emit)
        return 2

    max_iterations = config.get("max_iterations")
    iteration = 0
    processed = 0
    failed = 0
    emit_json(event_payload(
        "PRODUCTION_WORKER_STARTED",
        baseUrl=config["base_url"],
        workerId=config["worker_id"],
        maxIterations=max_iterations,
        tokenConfigured=bool(config.get("token")),
    ), emit=emit)

    while max_iterations is None or iteration < max_iterations:
        iteration += 1
        status, payload = request_fn(
            config["base_url"],
            config["worker_id"],
            token=config.get("token"),
            timeout=config["request_timeout"],
        )
        if ((payload or {}).get("error") and not (payload or {}).get("job")) or (status >= 400 and not (payload or {}).get("job")):
            failed += 1
            emit_json(event_payload(
                "PRODUCTION_WORKER_REQUEST_FAILED",
                httpStatus=status,
                error=payload.get("error") or {"code": "WORKER_HTTP_ERROR", "message": "Worker endpoint returned an error without a job payload."},
            ), emit=emit)
            if max_iterations is None:
                sleep_fn(config["sleep_seconds"])
                continue
            break

        job = (payload or {}).get("job")
        if not job:
            emit_json(event_payload(
                "PRODUCTION_WORKER_IDLE",
                httpStatus=status,
                reason=(payload or {}).get("reason"),
            ), emit=emit)
            if max_iterations is None:
                sleep_fn(config["sleep_seconds"])
                continue
            break

        processed += 1
        if status >= 400 or job.get("status") == "FAILED":
            failed += 1
        emit_json(event_payload(
            "PRODUCTION_WORKER_JOB_RESULT",
            httpStatus=status,
            jobId=job.get("jobId"),
            jobType=job.get("jobType"),
            status=job.get("status"),
            error=job.get("error"),
        ), emit=emit)
        if max_iterations is None:
            sleep_fn(0 if job.get("status") == "SUCCEEDED" else config["sleep_seconds"])

    emit_json(event_payload(
        "PRODUCTION_WORKER_STOPPED",
        iterations=iteration,
        processedJobs=processed,
        failedJobs=failed,
    ), emit=emit)
    return 2 if failed else 0


def build_parser():
    parser = argparse.ArgumentParser(description="Run the MatchOracle production worker loop.")
    parser.add_argument("--base-url", default=None, help="App base URL. Defaults to MATCHORACLE_APP_BASE_URL.")
    parser.add_argument("--worker-id", default=None, help="Worker id. Defaults to MATCHORACLE_WORKER_ID.")
    parser.add_argument("--token", default=None, help="Worker token. Defaults to MATCHORACLE_WORKER_TOKEN.")
    parser.add_argument("--sleep-seconds", type=float, default=None, help="Idle sleep interval.")
    parser.add_argument("--timeout", type=int, default=None, help="HTTP request timeout in seconds.")
    parser.add_argument("--max-iterations", type=int, default=None, help="Stop after this many loop iterations.")
    parser.add_argument("--once", action="store_true", help="Run one worker iteration and exit.")
    parser.add_argument(
        "--allow-missing-token-for-local-dev",
        action="store_true",
        help="Local-only escape hatch. Do not use this in production.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = build_worker_config(args)
    return run_worker_loop(config)


if __name__ == "__main__":
    sys.exit(main())
