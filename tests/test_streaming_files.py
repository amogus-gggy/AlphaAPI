from __future__ import annotations

from pathlib import Path

import pytest
from alphaapi import (
    Application,
    Client,
    FileResponse,
    HttpResponse,
    HttpResponseConflict,
    HttpResponseGatewayTimeout,
    HttpResponseGone,
    HttpResponseServiceUnavailable,
    HttpResponseTooManyRequests,
    SseResponse,
    StreamingHttpResponse,
    path,
)
from alphaapi.urls import clear_patterns


def _build(tmp_path: Path) -> Application:
    clear_patterns()
    data = tmp_path / "data.txt"
    data.write_text("0123456789")
    binary = tmp_path / "blob.bin"
    binary.write_bytes(bytes(range(10)))

    def sync_stream(request):
        def chunks():
            yield b"one"
            yield "two"
            yield {"three": 3}

        return StreamingHttpResponse(chunks(), content_type="text/plain")

    def async_stream(request):
        async def chunks():
            yield b"alpha"
            yield "beta"

        return StreamingHttpResponse(chunks(), content_type="text/plain")

    def factory_stream(request):
        return StreamingHttpResponse(
            lambda: iter([b"a", b"b"]), content_type="text/plain"
        )

    def sse(request):
        def events():
            yield {"event": "tick", "id": 1, "data": {"n": 1}}
            yield "plain"

        return SseResponse(events())

    def file(request):
        return FileResponse(data, request=request)

    def attachment(request):
        return FileResponse(data, as_attachment=True, filename="report.txt")

    def missing(request):
        return FileResponse(tmp_path / "nope.txt")

    async def boom(request):
        raise RuntimeError("kaboom")

    return Application(
        urlpatterns=[
            path("sync/", sync_stream, name="sync-stream"),
            path("async/", async_stream, name="async-stream"),
            path("factory/", factory_stream, name="factory-stream"),
            path("events/", sse, name="events"),
            path("file/", file, name="file"),
            path("attachment/", attachment, name="attachment"),
            path("missing/", missing, name="missing"),
            path("boom/", boom, name="boom"),
        ]
    )


def test_sync_streaming_response(tmp_path):
    with Client(_build(tmp_path)) as client:
        response = client.get("/sync/")
        assert response.status_code == 200
        assert response.content == b'onetwo{"three":3}'
        assert response.headers["content-type"].startswith("text/plain")


def test_async_streaming_response(tmp_path):
    with Client(_build(tmp_path)) as client:
        response = client.get("/async/")
        assert response.status_code == 200
        assert response.content == b"alphabeta"


def test_callable_stream_factory(tmp_path):
    with Client(_build(tmp_path)) as client:
        assert client.get("/factory/").content == b"ab"


def test_sse_response(tmp_path):
    with Client(_build(tmp_path)) as client:
        response = client.get("/events/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.content == b'event: tick\nid: 1\ndata: {"n":1}\n\nplain'


def test_streaming_response_rejects_sync_iteration_of_async_stream():
    async def chunks():
        yield b"x"

    response = StreamingHttpResponse(chunks())
    with pytest.raises(TypeError):
        list(response)


def test_file_response_full_and_head(tmp_path):
    with Client(_build(tmp_path)) as client:
        response = client.get("/file/")
        assert response.status_code == 200
        assert response.content == b"0123456789"
        assert response.headers["content-length"] == "10"
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["etag"].startswith('"')
        assert "last-modified" in response.headers

        head = client.head("/file/")
        assert head.status_code == 200
        assert head.content == b""
        assert head.headers["content-length"] == "10"


def test_file_response_conditional_requests(tmp_path):
    with Client(_build(tmp_path)) as client:
        full = client.get("/file/")
        etag = full.headers["etag"]
        modified = full.headers["last-modified"]

        assert client.get("/file/", headers={"if-none-match": etag}).status_code == 304
        assert (
            client.get("/file/", headers={"if-modified-since": modified}).status_code
            == 304
        )
        assert (
            client.get(
                "/file/", headers={"if-none-match": '"other"'}
            ).status_code
            == 200
        )


def test_file_response_ranges(tmp_path):
    with Client(_build(tmp_path)) as client:
        partial = client.get("/file/", headers={"range": "bytes=2-5"})
        assert partial.status_code == 206
        assert partial.content == b"2345"
        assert partial.headers["content-range"] == "bytes 2-5/10"
        assert partial.headers["content-length"] == "4"

        suffix = client.get("/file/", headers={"range": "bytes=-3"})
        assert suffix.status_code == 206
        assert suffix.content == b"789"

        invalid = client.get("/file/", headers={"range": "bytes=100-200"})
        assert invalid.status_code == 416
        assert invalid.headers["content-range"] == "bytes */10"
        assert invalid.content == b""


def test_file_response_attachment(tmp_path):
    with Client(_build(tmp_path)) as client:
        response = client.get("/attachment/")
        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        assert "report.txt" in response.headers["content-disposition"]


def test_file_response_missing_file(tmp_path):
    with Client(_build(tmp_path)) as client:
        response = client.get("/missing/")
        assert response.status_code == 500


def test_file_response_direct(tmp_path):
    data = tmp_path / "x.txt"
    data.write_text("abc")
    response = FileResponse(data)
    assert response.status_code == 200
    assert response.headers["content-length"] == "3"
    assert b"".join(response.streaming_content) == b"abc"

    with pytest.raises(FileNotFoundError):
        FileResponse(tmp_path / "absent.txt")


def test_sse_response_formats_values():
    response = SseResponse(iter([{"data": ["a", "b"]}, {"data": "line1\nline2"}]))
    body = b"".join(
        chunk.encode() if isinstance(chunk, str) else chunk
        for chunk in response.streaming_content
    )
    assert body == b'data: ["a","b"]\n\ndata: line1\ndata: line2\n\n'


def test_extra_status_response_classes():
    assert HttpResponseConflict().status_code == 409
    assert HttpResponseGone().status_code == 410
    assert HttpResponseTooManyRequests().status_code == 429
    assert HttpResponseServiceUnavailable().status_code == 503
    assert HttpResponseGatewayTimeout().status_code == 504
    assert HttpResponse("x").media_type == "text/html; charset=utf-8"


def test_debug_error_page(tmp_path, settings_override):
    from alphaapi._debug import format_exception

    assert "RuntimeError" in format_exception(RuntimeError("boom"))

    app = _build(tmp_path)
    settings_override(DEBUG=True)
    with Client(app) as client:
        response = client.get("/boom/")
        assert response.status_code == 500
        assert "RuntimeError" in response.text
        assert "kaboom" in response.text
