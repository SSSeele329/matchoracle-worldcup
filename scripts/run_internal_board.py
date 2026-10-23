#!/usr/bin/env python3
"""Run the local internal test board with an env file."""

import argparse
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_ENV_FILE = os.path.join(PROJECT_ROOT, "deploy", "local.internal.env")


def load_env_file(path):
    values = {}
    if not path or not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def build_parser():
    parser = argparse.ArgumentParser(description="Run MatchOracle's local internal test board.")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE, help="Local env file path.")
    parser.add_argument("--port", default="5020", help="Flask port.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    env = os.environ.copy()
    env.update(load_env_file(args.env_file))
    env["PORT"] = str(args.port)
    command = [sys.executable, "app.py"]
    return subprocess.call(command, cwd=PROJECT_ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
