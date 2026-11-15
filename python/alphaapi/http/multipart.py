"""Multipart/form-data parsing and uploaded-file helpers."""
from __future__ import annotations

import io
from email.parser import BytesParser
from email.policy import HTTP
from typing import Any, Iterator


class UploadedFile:
    """A file uploaded through a ``multipart/form-data`` request."""

    def __init__(
        self,
        name: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        *,
        headers: Any = None,
    ) -> None:
        self.field_name = name
        self.name = filename
        self.filename = filename
        self.content_type = content_type
        self.body = content
        self.headers = headers
        self.file = io.BytesIO(content)

    @property
    def size(self) -> int:
        return len(self.body)

    def read(self, size: int = -1) -> bytes:
        return self.file.read(size)

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self.file.seek(offset, whence)

    def tell(self) -> int:
        return self.file.tell()

    def chunks(self, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        self.file.seek(0)
        while True:
            chunk = self.file.read(chunk_size)
            if not chunk:
                break
            yield chunk
        self.file.seek(0)

    def multiple_chunks(self, chunk_size: int = 64 * 1024) -> bool:
        return self.size > chunk_size

    def close(self) -> None:
        self.file.close()

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return f"<UploadedFile name={self.name!r} size={self.size}>"


def parse_multipart(
    body: bytes,
    content_type: str,
) -> tuple[list[tuple[str, str]], dict[str, list[UploadedFile]]]:
    """Return ``(text_fields, files)`` for a multipart payload.

    ``text_fields`` is a list of ``(name, value)`` pairs so repeated form fields
    can be preserved.  Files are grouped by field name.
    """
    if "multipart/form-data" not in content_type.lower():
        return [], {}

    header = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8", "replace")
    try:
        message = BytesParser(policy=HTTP).parsebytes(header + body)
    except Exception:
        return [], {}

    if not message.is_multipart():
        return [], {}

    fields: list[tuple[str, str]] = []
    files: dict[str, list[UploadedFile]] = {}

    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"

        if filename is not None:
            uploaded = UploadedFile(
                name=name,
                filename=filename,
                content=payload,
                content_type=part.get_content_type(),
                headers=part,
            )
            files.setdefault(name, []).append(uploaded)
        else:
            fields.append((name, payload.decode(charset, "replace")))

    return fields, files


__all__ = ["UploadedFile", "parse_multipart"]
