"""Development error-page rendering used by the Rust core when DEBUG=True."""
from __future__ import annotations

import html
import traceback
from typing import Any


def format_exception(exception: Any) -> str:
    """Return an HTML traceback for an exception instance."""
    error_type = type(exception)
    lines = traceback.format_exception(
        error_type, exception, getattr(exception, "__traceback__", None)
    )
    traceback_text = "".join(lines)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>{html.escape(error_type.__name__)}</title>
    <style>
      body {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
              margin: 2rem; background: #fff7f7; color: #1f1f1f; }}
      h1 {{ font-family: system-ui, sans-serif; color: #b00020; }}
      pre {{ background: #1f1f1f; color: #f5f5f5; padding: 1rem;
             overflow: auto; border-radius: 6px; }}
    </style>
  </head>
  <body>
    <h1>{html.escape(error_type.__name__)}: {html.escape(str(exception))}</h1>
    <p>The server is running in <strong>DEBUG</strong> mode. Disable it in production.</p>
    <pre>{html.escape(traceback_text)}</pre>
  </body>
</html>"""


def format_request_exception(request: Any, exception: Any) -> str:
    page = format_exception(exception)
    summary = (
        f"<p><strong>{html.escape(str(getattr(request, 'method', '')))} "
        f"{html.escape(str(getattr(request, 'path', '')))}</strong></p>"
    )
    return page.replace("<body>", "<body>" + summary, 1)


__all__ = ["format_exception", "format_request_exception"]
