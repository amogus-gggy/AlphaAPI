"""A small, zero-dependency HTTP benchmark comparing AlphaAPI and FastAPI.

This is intentionally simple: a pool of Python threads keeps a persistent
connection open and issues requests in a loop.  It is not a replacement for
`wrk`/`oha`, but it gives a useful relative signal on the same machine.

Usage:
    python benchmarks/bench.py
    python benchmarks/bench.py --requests 20000 --concurrency 32 --path /json
"""
from __future__ import annotations

import argparse
import http.client
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(port: int, timeout: float = 20.0) -> None:
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


def worker(
    port: int,
    path: str,
    count: int,
    barrier: threading.Barrier,
    results: list[int],
    errors: list[int],
) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
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
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    connection.close()
    results[0] = count
    errors[0] = local_errors


def run_load(port: int, path: str, total_requests: int, concurrency: int) -> Result:
    per_thread = max(1, total_requests // concurrency)
    actual = per_thread * concurrency
    barrier = threading.Barrier(concurrency + 1)
    done = [0]
    errors = [0]
    threads = [
        threading.Thread(
            target=worker,
            args=(port, path, per_thread, barrier, done, errors),
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
    elapsed = time.perf_counter() - started
    return Result("", actual, elapsed, errors[0])


def run_server(server: str, port: int, env: dict[str, str]) -> subprocess.Popen:
    command = [sys.executable, str(ROOT / server)]
    child_env = os.environ.copy()
    child_env.update(env)
    child_env["PORT"] = str(port)
    return subprocess.Popen(
        command,
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
    env: dict[str, str] | None = None,
) -> Result:
    port = free_port()
    process = run_server(server, port, env or {})
    try:
        wait_ready(port)
        # Warm up paths, JITs and connection pools.
        run_load(port, path, max(200, concurrency * 10), concurrency)
        result = run_load(port, path, requests, concurrency)
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
    parser.add_argument("--requests", type=int, default=10000)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--path", default="/json")
    parser.add_argument("--fastapi", action="store_true", help="also benchmark FastAPI")
    args = parser.parse_args()

    scenarios = [("AlphaAPI", "server_alpha.py", {})]
    if args.fastapi:
        scenarios.append(("FastAPI + uvicorn", "server_fastapi.py", {}))

    print(
        f"{args.path}  requests={args.requests}  concurrency={args.concurrency}"
    )
    print(f"{'server':22} {'req/s':>12} {'p50 total':>12} {'errors':>8}")
    print("-" * 58)

    for name, server, env in scenarios:
        result = benchmark(name, server, args.path, args.requests, args.concurrency, env)
        print(
            f"{name:22} {result.rps:12,.0f} {result.seconds:11.3f}s {result.errors:8d}"
        )


if __name__ == "__main__":
    main()
