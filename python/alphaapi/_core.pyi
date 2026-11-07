from collections.abc import Awaitable, Callable, Mapping
from typing import Any

class Request:
    method: str
    path: str
    query_string: str
    client: str | None
    headers: dict[str, str]
    params: dict[str, str]
    query_params: dict[str, Any]
    body: bytes
    def text(self) -> str: ...
    def json(self) -> Any: ...
    def header(self, name: str, default: Any = ...) -> Any: ...
    def query_param(self, name: str, default: Any = ...) -> Any: ...

class Response:
    status_code: int
    headers: dict[str, str]
    body: bytes
    media_type: str | None
    def __init__(
        self,
        content: Any = ...,
        status_code: int = ...,
        headers: Mapping[str, str] | None = ...,
        media_type: str | None = ...,
    ) -> None: ...

class AppCore:
    def __init__(self) -> None: ...
    def add_route(
        self,
        method: str,
        path: str,
        handler: Callable[..., Any],
        spec: dict[str, Any],
    ) -> None: ...
    def add_exception_handler(
        self,
        exc_type: type[BaseException],
        handler: Callable[..., Any],
    ) -> None: ...
    def set_http_exception_type(self, exc_type: type[BaseException]) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
    def run(
        self,
        host: str = ...,
        port: int = ...,
        workers: int | None = ...,
        max_body_size: int | None = ...,
        access_log: bool | None = ...,
    ) -> None: ...
