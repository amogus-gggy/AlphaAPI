"""Command line interface: ``alphaapi runserver module:app``."""
from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

from .scaffold import ScaffoldError, _camel_case, startapp, startproject


def load_app(target: str):
    module_name, separator, attribute = target.partition(":")
    if not separator or not module_name or not attribute:
        raise SystemExit(
            f"invalid app target {target!r}; expected something like 'project.app:app'"
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


def _command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "alphaapi.cli",
        "runserver",
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
    if args.settings:
        command += ["--settings", args.settings]
    return command


def _run_with_reload(args: argparse.Namespace) -> None:
    command = _command(args)
    if args.settings:
        os.environ["ALPHAAPI_SETTINGS_MODULE"] = args.settings

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


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("app", help="application import path, e.g. project.app:app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--max-body-size", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--access-log", action="store_true")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--settings",
        default=None,
        help="settings module, e.g. project.settings",
    )


def _startproject(args: argparse.Namespace) -> None:
    try:
        root = startproject(args.name, args.directory)
    except ScaffoldError as error:
        raise SystemExit(str(error)) from error
    print(f"Project {args.name!r} created at {root}")
    print()
    print("Next steps:")
    print(f"  cd {root}")
    print("  python manage.py --port 8000")


def _startapp(args: argparse.Namespace) -> None:
    try:
        root = startapp(args.name, args.directory)
    except ScaffoldError as error:
        raise SystemExit(str(error)) from error
    print(f"App {args.name!r} created at {root}")
    print()
    print("Next steps:")
    print(f'  add "{args.name}.apps.{_camel_case(args.name)}Config" to INSTALLED_APPS')
    print(f'  add path("{args.name}/", include("{args.name}.urls")) to your URLconf')


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="alphaapi", description="AlphaAPI server")
    subparsers = parser.add_subparsers(dest="command", required=True)

    runserver_parser = subparsers.add_parser("runserver", help="run an application")
    _add_run_options(runserver_parser)

    # Kept as a short alias for people coming from the earlier preview API.
    run_parser = subparsers.add_parser("run", help=argparse.SUPPRESS)
    _add_run_options(run_parser)

    startproject_parser = subparsers.add_parser(
        "startproject", help="create a new AlphaAPI project"
    )
    startproject_parser.add_argument("name", help="project package name")
    startproject_parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="destination directory (defaults to ./<name>)",
    )

    startapp_parser = subparsers.add_parser(
        "startapp", help="create a new reusable app"
    )
    startapp_parser.add_argument("name", help="app package name")
    startapp_parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="destination directory (defaults to the current directory)",
    )

    args = parser.parse_args(argv)

    if args.command == "startproject":
        _startproject(args)
        return
    if args.command == "startapp":
        _startapp(args)
        return

    if args.command in {"runserver", "run"}:
        if args.settings:
            os.environ["ALPHAAPI_SETTINGS_MODULE"] = args.settings
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
