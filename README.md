# AlphaAPI

A small, FastAPI-inspired Python web framework with an HTTP core written in Rust.

> Status: early preview. The public API is intentionally small and may evolve.

## Install (from source)

```bash
python -m venv .venv
. .venv/bin/activate
pip install maturin
maturin develop --release
```

## Quick start

```python
from alphaapi import Alpha

app = Alpha(title="Demo")


@app.get("/")
def read_root():
    return {"hello": "world"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}


@app.post("/items", status_code=201)
def create_item(item: dict):
    return {"created": item}


if __name__ == "__main__":
    app.run(port=8000)
```

```bash
python main.py
# or
alphaapi run main:app --port 8000
```

Open <http://127.0.0.1:8000/docs> for the generated Swagger UI.

## FastAPI compatibility mode (experimental)

> **Warning:** this is a **backward-compatibility mod**. It monkeypatches the
> `fastapi` module so existing code can run on AlphaAPI. It **can degrade
> performance**, **may not be optimal**, and does not implement every
> FastAPI/Starlette feature or edge case. Unsupported features may be ignored,
> partially emulated, or raise an error. Prefer the native `alphaapi` API for
> production workloads.

```python
import alphaapi.compat.fastapi as compat

compat.install()  # emits a CompatibilityWarning

# Existing FastAPI-style code now works:
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

app = FastAPI(title="Compat Demo")


def get_token() -> str:
    return "demo-token"


@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = Query(default=None), token: str = Depends(get_token)):
    return {"item_id": item_id, "q": q, "token": token}


if __name__ == "__main__":
    app.run(port=8000)  # AlphaAPI's Rust server
```

Existing `uvicorn module:app` deployments also work: the compat app lazily
starts AlphaAPI's Rust server and proxies ASGI requests to it. That proxy hop is
one of the reasons compatibility mode is slower than native AlphaAPI.

Install it before importing application modules (or at least before creating
the `FastAPI` app):

```python
import alphaapi.compat.fastapi as compat

compat.install()  # warnings.warn(..., CompatibilityWarning)
```

Pass `warn=False` to silence the warning (not recommended).

**What works reasonably well**

- `FastAPI`/`APIRouter`, route decorators, prefixes, tags, `include_router`
- Path/query/header/body parameters, aliases, defaults, Pydantic validation
  (delegated to AlphaAPI's Rust core where possible)
- `Depends`/`Security` with simple (sync or async) dependencies
- `Cookie` parameters (parsed in Python), `Request` adapter, `BackgroundTasks`
  container (tasks are not auto-executed)
- `HTTPException`, custom exception handlers, `status`
- JSON/plain-text/HTML/redirect responses, response classes, OpenAPI/docs
- `uvicorn module:app` via a local ASGI-to-Rust proxy
- A minimal `TestClient`, `jsonable_encoder`, common security marker classes,
  middleware/static/templating placeholders that warn when used

**Known limitations**

- `response_model` is accepted but not used for validation/serialization
- Form/file uploads, WebSockets, middleware execution, static mounts, lifespan
  composition, background task execution and response streaming are incomplete
- Compatibility routes that need Python-side binding (dependencies, cookies,
  forms, `Request`) bypass AlphaAPI's fast Rust binding and are slower
- Semantics may differ subtly from FastAPI/Starlette


## Features

- Rust-powered HTTP/1.1 server built on `hyper` and `tokio`
- Fast route matching via `matchit`
- `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS` and `HEAD` routes
  (including automatic `OPTIONS`/`405`/`HEAD` handling)
- Automatic path, query and header parameter conversion
- JSON body parsing and Pydantic/dataclass model validation
- Sync and `async def` handlers
- Automatic JSON serialization, plus `str`, `bytes`, `JSONResponse`,
  `PlainTextResponse`, `HTMLResponse`, `RedirectResponse` and raw `Response`
- `HTTPException` and custom exception handlers
- Startup/shutdown hooks
- Composable `APIRouter`s with prefixes and tags
- OpenAPI 3.1 schema + Swagger UI
- Zero required Python dependencies

## API

```python
from alphaapi import (
    Alpha, APIRouter, Request, Response,
    JSONResponse, PlainTextResponse, HTMLResponse, RedirectResponse,
    HTTPException, Query, Path, Header, Body,
)
```

### Parameters

```python
@app.get("/search")
def search(
    q: str,
    limit: int = Query(10, description="Maximum results"),
    x_token: str = Header(...),
):
    ...
```

- Path parameters are inferred from `{name}` in the route.
- Scalars (`str`, `int`, `float`, `bool`) are inferred as query parameters.
- Pydantic models and dataclasses are inferred as the JSON body.
- Use `Request` as a type annotation to receive the raw request object.
- `Query`, `Path`, `Header` and `Body` markers also work inside
  `typing.Annotated`.

### Responses

Handlers may return:

| Return value       | Response                          |
| ------------------ | --------------------------------- |
| `dict`, `list`, …  | JSON                              |
| `str`              | `text/plain; charset=utf-8`       |
| `bytes`            | `application/octet-stream`        |
| `Response`         | full control (status/headers/body)|
| Pydantic model     | JSON                              |
| `None`             | JSON `null`                       |

Raise `HTTPException(status_code=404, detail="Not found")` for errors.

### Async handlers

```python
@app.get("/async")
async def async_handler():
    await asyncio.sleep(0.1)
    return {"ok": True}
```

Async handlers run on a dedicated Python asyncio event loop, while the HTTP
server and routing stay on Rust threads.

## Benchmarks

See [`benchmarks/`](benchmarks/) for a comparison against FastAPI. The bundled
runner compiles a tiny std-only Rust load generator (`benchmarks/loadgen.rs`) so
the results are not capped by a GIL-bound Python client:

```bash
pip install fastapi uvicorn
python benchmarks/bench.py --fastapi
```

Output on a 2-core Celeron N3350 (5,000 requests, concurrency 16, `/json`):

```
server                        req/s         time   errors
----------------------------------------------------------
AlphaAPI                      9,363       0.534s        0
FastAPI + uvicorn               415      12.042s        0
```

That is roughly 20x the throughput of FastAPI + uvicorn on the same machine.
Absolute numbers on this box swing between ~2.6k and ~9.4k req/s because the
CPU aggressively scales its clock; the relative gap stays around 12-22x. For
reference, a hand-written blocking Rust TCP server measured ~12k req/s with
the same load generator, so AlphaAPI is within ~25% of a raw Rust HTTP loop
while running a Python handler on every request.

Use `--python-load` to fall back to the dependency-free Python load client.

## Testing

```bash
pytest -q
```

The suite covers routing, every HTTP method, typed path/query/header
parameters, query-string decoding, JSON and Pydantic bodies, dataclasses,
sync and async handlers, JSON/plain-text/HTML/redirect/raw responses,
exceptions, OpenAPI/docs, routers, lifecycle hooks and request limits.

## How it works

The Python layer performs signature introspection once at registration time
and hands a compact route specification to the Rust core. At request time the
Rust server parses and routes the request, builds typed Python arguments, and
calls the handler. Response serialization (dict/list → JSON) also happens in
Rust.

### Hot-path design

- **Zero-copy bodies.** Request bodies are kept as reference-counted `Bytes`.
  A single-frame body (the common case) is passed through without copying, and
  response bodies are handed to `hyper` as `Bytes` without a conversion copy.
- **Direct JSON encoding.** The Rust serializer walks Python dicts/lists and
  writes JSON bytes directly, avoiding a `Python → serde_json::Value → bytes`
  round-trip and its intermediate allocations. Only unusual objects fall back
  to the Python `to_builtin` helper.
- **Lazy request materialization.** Headers, query parameters, path-parameter
  maps and the full request object are only built when the route (or an
  exception handler) actually needs them. Simple routes allocate no maps.
- **Precomputed binding metadata.** Header names are lowercased once at
  registration, and `HeaderMap` lookups use borrowed strings with no per-request
  key allocation.
- **HTTP/1 fast path.** Connections use `hyper`'s HTTP/1 builder directly
  (no protocol auto-detection) with `TCP_NODELAY` and pipelining enabled.
- **Short path to Python.** Sync handlers run inline on the Tokio worker via a
  direct GIL attach rather than paying for a blocking-pool round-trip; async
  handlers only create/serialize their coroutine inline and await on the
  dedicated asyncio loop.
- **GIL-aware worker count.** Tokio worker threads default to half the
  available cores (minimum one). Because Python execution is serialized by the
  GIL, extra workers mostly add lock contention; raise `workers=` if your sync
  handlers block on I/O.

## Limits

- One body parameter per handler.
- Custom exception handlers run synchronously.
- No dependency injection (`Depends`) yet.
- No built-in WebSocket support.
- HTTP/2 and TLS are not built in; place the server behind a reverse proxy if
  you need them.
- Sync handlers should stay short. Long CPU-bound handlers execute while
  holding the GIL, so keep heavy work in async handlers or another process.
- Pydantic is optional; without it, use dataclasses or plain dicts.

## License

MIT
