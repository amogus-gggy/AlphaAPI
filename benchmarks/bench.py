"""A local HTTP benchmark comparing AlphaAPI and FastAPI.

By default this builds and uses the small std-only Rust load generator in
``benchmarks/loadgen.rs`` (no extra dependencies) so the measurement is not
capped by a GIL-bound Python client.  Pass ``--python-load`` to fall back to the
pure-Python loader.

Usage:
    python benchmarks/bench.py
    python benchmarks/bench.py --requests 20000 --concurrency 16 --fastapi
"""
from __future__ import annotations

import argparse
import http.client
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"server on port {port} did not start")


@dataclass
class Result:
    name: str
    requests: int
    seconds: float
    errors: int

    @property
    def rps(self) -> float:
        return self.requests / self.seconds


def ensure_loadgen() -> str | None:
    """Compile the Rust load generator once, if rustc is available."""
    source = ROOT / "loadgen.rs"
    if not source.exists():
        return None
    target = Path(tempfile.gettempdir()) / "alphaapi-loadgen"
    try:
        if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(
                ["rustc", "-O", str(source), "-o", str(target)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return str(target)
    except Exception:
        return None


def run_load_rust(
    loadgen: str, port: int, path: str, requests: int, concurrency: int
) -> Result:
    output = subprocess.run(
        [loadgen, "127.0.0.1", str(port), path, str(requests), str(concurrency)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    # "2323 req/s  8.609s  20000 requests  0 errors"
    parts = output.split()
    seconds = float(parts[2].rstrip("s"))
    errors = int(parts[-2])
    return Result("", requests, seconds, errors)


# -- pure-Python fallback --------------------------------------------------


def _worker(
    port: int,
    path: str,
    count: int,
    barrier: threading.Barrier,
    errors: list[int],
) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    local_errors = 0
    barrier.wait()
    for _ in range(count):
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            response.read()
            if response.status != 200:
                local_errors += 1
        except Exception:
            local_errors += 1
            try:
                connection.close()
            except Exception:
                pass
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    connection.close()
    errors[0] = local_errors


def run_load_python(port: int, path: str, total: int, concurrency: int) -> Result:
    per_thread = max(1, total // concurrency)
    actual = per_thread * concurrency
    barrier = threading.Barrier(concurrency + 1)
    errors = [0]
    threads = [
        threading.Thread(
            target=_worker,
            args=(port, path, per_thread, barrier, errors),
            daemon=True,
        )
        for _ in range(concurrency)
    ]
    for thread in threads:
        thread.start()

    started = time.perf_counter()
    barrier.wait()
    for thread in threads:
        thread.join()
    return Result("", actual, time.perf_counter() - started, errors[0])


# -- servers ---------------------------------------------------------------


def run_server(server: str, port: int, env: dict[str, str]) -> subprocess.Popen:
    child_env = os.environ.copy()
    child_env.update(env)
    child_env["PORT"] = str(port)
    return subprocess.Popen(
        [sys.executable, str(ROOT / server)],
        cwd=str(ROOT),
        env=child_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def benchmark(
    name: str,
    server: str,
    path: str,
    requests: int,
    concurrency: int,
    loadgen: str | None,
    env: dict[str, str] | None = None,
) -> Result:
    port = free_port()
    process = run_server(server, port, env or {})
    try:
        wait_ready(port)
        run = (
            (lambda n: run_load_rust(loadgen, port, path, n, concurrency))
            if loadgen
            else (lambda n: run_load_python(port, path, n, concurrency))
        )
        # Warm up paths, connection pools and the Python thread state cache.
        run(max(200, concurrency * 10))
        result = run(requests)
        result.name = name
        return result
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=20000)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--path", default="/json")
    parser.add_argument("--fastapi", action="store_true", help="also benchmark FastAPI")
    parser.add_argument(
        "--python-load",
        action="store_true",
        help="use the pure-Python load client instead of the Rust one",
    )
    args = parser.parse_args()

    loadgen = None if args.python_load else ensure_loadgen()
    client = "Rust loadgen" if loadgen else "Python threads"

    scenarios = [("AlphaAPI", "server_alpha.py", {})]
    if args.fastapi:
        scenarios.append(("FastAPI + uvicorn", "server_fastapi.py", {}))

    print(f"{args.path}  requests={args.requests}  concurrency={args.concurrency}  client={client}")
    print(f"{'server':22} {'req/s':>12} {'time':>12} {'errors':>8}")
    print("-" * 58)

    for name, server, env in scenarios:
        result = benchmark(
            name,
            server,
            args.path,
            args.requests,
            args.concurrency,
            loadgen,
            env,
        )
        print(f"{name:22} {result.rps:12,.0f} {result.seconds:11.3f}s {result.errors:8d}")


if __name__ == "__main__":
    main()
