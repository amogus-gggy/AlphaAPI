from __future__ import annotations

import json

from alphaapi import Application, Client, HttpResponse, JsonResponse, path
from alphaapi.http.multipart import UploadedFile, parse_multipart
from alphaapi.urls import clear_patterns


def _multipart(boundary: str, parts: list[tuple[str, str, bytes | None, str | None]]) -> bytes:
    chunks: list[bytes] = []
    for name, value, filename, content_type in parts:
        chunks.append(f"--{boundary}\r\n".encode())
        if filename is None:
            chunks.append(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            )
            chunks.append(value.encode())
        else:
            chunks.append(
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode()
            )
            if content_type:
                chunks.append(f"Content-Type: {content_type}\r\n".encode())
            chunks.append(b"\r\n")
            chunks.append(value.encode())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks)


def test_parse_multipart_fields_and_files():
    body = _multipart(
        "boundary",
        [
            ("title", "Hello", None, None),
            ("title", "World", None, None),
            ("file", "file-data", "a.txt", "text/plain"),
            ("file", "more-data", "b.txt", "text/plain"),
        ],
    )
    fields, files = parse_multipart(
        body, "multipart/form-data; boundary=boundary"
    )
    assert fields == [("title", "Hello"), ("title", "World")]
    assert [item.filename for item in files["file"]] == ["a.txt", "b.txt"]
    assert files["file"][0].content_type == "text/plain"


def test_parse_multipart_ignores_non_multipart():
    assert parse_multipart(b"a=1", "application/x-www-form-urlencoded") == ([], {})


def test_uploaded_file_api():
    uploaded = UploadedFile("file", "a.txt", b"0123456789", "text/plain")
    assert uploaded.field_name == "file"
    assert uploaded.name == "a.txt"
    assert uploaded.size == 10
    assert len(uploaded) == 10
    assert uploaded.read(3) == b"012"
    uploaded.seek(0)
    assert list(uploaded.chunks(chunk_size=4)) == [b"0123", b"4567", b"89"]
    assert uploaded.multiple_chunks(chunk_size=4) is True
    assert uploaded.multiple_chunks(chunk_size=64) is False
    uploaded.close()


def _app() -> Application:
    clear_patterns()

    async def upload(request):
        files = request.FILES
        mapped = {}
        for name, value in files.items():
            values = value if isinstance(value, list) else [value]
            mapped[name] = [
                {
                    "filename": item.filename,
                    "content": item.read().decode(),
                    "type": item.content_type,
                }
                for item in values
            ]
        return JsonResponse({"post": request.POST.dict(), "files": mapped})

    async def urlencoded(request):
        return JsonResponse(
            {
                "post": request.POST.dict(),
                "lists": request.POST.getlist("tag"),
                "files": request.FILES,
            }
        )

    return Application(
        urlpatterns=[
            path("upload/", upload, name="upload"),
            path("urlencoded/", urlencoded, name="urlencoded"),
        ]
    )


def test_request_files_from_multipart_upload():
    body = _multipart(
        "xyz",
        [
            ("title", "Hello", None, None),
            ("file", "file-data", "a.txt", "text/plain"),
        ],
    )
    with Client(_app()) as client:
        response = client.post(
            "/upload/",
            body=body,
            headers={"content-type": "multipart/form-data; boundary=xyz"},
        )
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["post"] == {"title": "Hello"}
        assert data["files"] == {
            "file": [{"filename": "a.txt", "content": "file-data", "type": "text/plain"}]
        }


def test_request_files_repeated_field_name():
    body = _multipart(
        "xyz",
        [
            ("file", "one", "a.txt", "text/plain"),
            ("file", "two", "b.txt", "text/plain"),
        ],
    )
    with Client(_app()) as client:
        response = client.post(
            "/upload/",
            body=body,
            headers={"content-type": "multipart/form-data; boundary=xyz"},
        )
        files = json.loads(response.content)["files"]["file"]
        assert [item["filename"] for item in files] == ["a.txt", "b.txt"]


def test_urlencoded_form_still_supported():
    with Client(_app()) as client:
        response = client.post("/urlencoded/", data={"tag": "a", "name": "n"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["post"] == {"tag": "a", "name": "n"}
        assert data["files"] == {}


def test_uploaded_file_content_type_and_repr():
    uploaded = UploadedFile("f", "x.bin", b"\x00\x01")
    assert uploaded.content_type == "application/octet-stream"
    assert "UploadedFile" in repr(uploaded)
    response = HttpResponse(b"")
    assert response.status_code == 200
