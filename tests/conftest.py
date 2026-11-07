from __future__ import annotations

import http.client
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any

import pytest


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class RunningServer:
    app: Any
    port: int
    thread: threading.Thread
    base_url: str

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            payload = response.read()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, payload
        finally:
            connection.close()

    def stop(self) -> None:
        self.app.stop()
        self.thread.join(timeout=10)
        assert not self.thread.is_alive(), "server did not stop"


@pytest.fixture(scope="session")
def start_server():
    servers: list[RunningServer] = []

    def start(app, port: int | None = None) -> RunningServer:
        port = port or free_port()
        thread = threading.Thread(
            target=app.run,
            kwargs={"host": "127.0.0.1", "port": port},
            daemon=True,
        )
        thread.start()

        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.02)
        else:
            raise RuntimeError("server did not start")

        server = RunningServer(app, port, thread, f"http://127.0.0.1:{port}")
        servers.append(server)
        return server

    yield start

    for server in servers:
        if server.thread.is_alive():
            server.stop()
