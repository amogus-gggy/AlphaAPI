"""Command line interface: ``alphaapi run module:app``."""
from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
import time
from pathlib import Path


def load_app(target: str):
    module_name, separator, attribute = target.partition(":")
    if not separator or not module_name or not attribute:
        raise SystemExit(
            f"invalid app target {target!r}; expected something like 'main:app'"
        )

    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute)
    except AttributeError as error:
        raise SystemExit(f"{module_name!r} has no attribute {attribute!r}") from error


def _snapshot(root: Path) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    skip = {".git", ".venv", "venv", "__pycache__", "target", "node_modules", "dist", "build"}
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [name for name in subdirectories if name not in skip]
        for filename in files:
            if filename.endswith((".py", ".toml")):
                path = Path(directory) / filename
                try:
                    snapshot[str(path)] = path.stat().st_mtime
                except OSError:
                    pass
    return snapshot


def _run_with_reload(args: argparse.Namespace) -> None:
    command = [
        sys.executable,
        "-m",
        "alphaapi.cli",
        "run",
        args.app,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--max-body-size",
        str(args.max_body_size),
    ]
    if args.workers:
        command += ["--workers", str(args.workers)]
    if args.access_log:
        command.append("--access-log")

    root = Path.cwd()
    process = subprocess.Popen(command)
    snapshot = _snapshot(root)
    try:
        while process.poll() is None:
            time.sleep(0.4)
            current = _snapshot(root)
            if current != snapshot:
                snapshot = current
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                time.sleep(0.15)
                process = subprocess.Popen(command)
    except KeyboardInterrupt:
        pass
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="alphaapi", description="AlphaAPI server")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run an application")
    run_parser.add_argument("app", help="application import path, e.g. main:app")
    run_parser.add_argument("--host", default="127.0.0.1")
    run_parser.add_argument("--port", type=int, default=8000)
    run_parser.add_argument("--workers", type=int, default=None)
    run_parser.add_argument("--max-body-size", type=int, default=16 * 1024 * 1024)
    run_parser.add_argument("--access-log", action="store_true")
    run_parser.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "run":
        if args.reload:
            _run_with_reload(args)
            return
        app = load_app(args.app)
        app.run(
            host=args.host,
            port=args.port,
            workers=args.workers,
            max_body_size=args.max_body_size,
            access_log=args.access_log,
        )


if __name__ == "__main__":
    main()
