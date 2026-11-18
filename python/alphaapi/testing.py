"""An in-process-style HTTP test client.

The client starts the application on an ephemeral loopback port in a background
thread, so it exercises the real Rust/hyper stack without requiring callers to
manage ports or server threads themselves.
"""
from __future__ import annotations

import http.client
import json as json_module
import socket
import threading
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class ClientResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self) -> Any:
        return json_module.loads(self.content)

    def __iter__(self) -> Iterator[Any]:
        # Tuple unpacking mirrors the lightweight clients used in tests.
        yield self.status_code
        yield self.headers
        yield self.content


class Client:
    """A Django/FastAPI-style test client for an ``Application``."""

    def __init__(self, app: Any, host: str = "127.0.0.1", timeout: float = 10.0) -> None:
        self.app = app
        self.host = host
        self.timeout = timeout
        self.port: int | None = None
        self._thread: threading.Thread | None = None
        self._cookies: dict[str, str] = {}

    def _start(self) -> None:
        if self._thread is not None:
            return

        # Releasing a probed port and then binding it is inherently racy when
        # several clients start in parallel.  Retry with a fresh port instead
        # of failing the test run.
        for _ in range(5):
            self.port = _free_port()
            self._thread = threading.Thread(
                target=self.app.run,
                kwargs={"host": self.host, "port": self.port},
                daemon=True,
                name="alphaapi-test-client",
            )
            self._thread.start()

            deadline = time.time() + self.timeout
            while time.time() < deadline:
                if not self._thread.is_alive():
                    break
                try:
                    with socket.create_connection((self.host, self.port), timeout=0.1):
                        return
                except OSError:
                    time.sleep(0.01)

            self.app.stop()
            self._thread.join(timeout=self.timeout)
            self._thread = None

        raise RuntimeError("test server did not start")

    def close(self) -> None:
        if self._thread is None:
            return
        self.app.stop()
        self._thread.join(timeout=self.timeout)
        self._thread = None
        self.port = None

    def __enter__(self) -> Client:
        self._start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | str | None = None,
        data: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
    ) -> ClientResponse:
        self._start()
        assert self.port is not None

        if json is not None:
            body = json_module.dumps(json).encode("utf-8")
            headers = {"content-type": "application/json", **dict(headers or {})}
        elif data is not None:
            from urllib.parse import urlencode

            body = urlencode(data).encode("utf-8")
            headers = {
                "content-type": "application/x-www-form-urlencoded",
                **dict(headers or {}),
            }
        elif isinstance(body, str):
            body = body.encode("utf-8")

        request_headers = dict(headers or {})
        jar = dict(self._cookies)
        jar.update(cookies or {})
        if jar and "cookie" not in {key.lower() for key in request_headers}:
            request_headers["cookie"] = "; ".join(
                f"{key}={value}" for key, value in jar.items()
            )

        connection = http.client.HTTPConnection(
            self.host, self.port, timeout=self.timeout
        )
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            payload = response.read()
        finally:
            connection.close()

        response_headers: dict[str, str] = {}
        set_cookies = response.headers.get_all("Set-Cookie") or []
        for raw in set_cookies:
            parsed = SimpleCookie()
            try:
                parsed.load(raw)
            except Exception:
                continue
            for name, morsel in parsed.items():
                if morsel.value:
                    self._cookies[name] = morsel.value
                else:
                    self._cookies.pop(name, None)
        for key, value in response.getheaders():
            lowered = key.lower()
            if lowered == "set-cookie" and lowered in response_headers:
                # Set-Cookie is not a comma-joinable field.  Keep the first
                # value; cookies are tracked separately in the client jar.
                continue
            response_headers[lowered] = (
                f"{response_headers[lowered]}, {value}"
                if lowered in response_headers
                else value
            )

        return ClientResponse(response.status, response_headers, payload)

    def get(self, path: str, **kwargs: Any) -> ClientResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> ClientResponse:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> ClientResponse:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> ClientResponse:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> ClientResponse:
        return self.request("DELETE", path, **kwargs)

    def head(self, path: str, **kwargs: Any) -> ClientResponse:
        return self.request("HEAD", path, **kwargs)

    def options(self, path: str, **kwargs: Any) -> ClientResponse:
        return self.request("OPTIONS", path, **kwargs)


__all__ = ["Client", "ClientResponse"]
