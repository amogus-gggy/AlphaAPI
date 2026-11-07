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

## Features

- Rust-powered HTTP/1.1 + HTTP/2 server built on `hyper` and `tokio`
- Fast route matching via `matchit`
- Automatic path, query and header parameter conversion
- JSON body parsing and Pydantic/dataclass model validation
- Sync and `async def` handlers
- Automatic JSON serialization (plus `str`, `bytes` and response classes)
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

See [`benchmarks/`](benchmarks/) for a simple comparison against FastAPI.
Run:

```bash
pip install fastapi uvicorn
python benchmarks/bench.py --fastapi
```

On a 2-core machine, a small local run (5,000 requests, 16 threads) measured
roughly 440 req/s for AlphaAPI versus 170 req/s for FastAPI + uvicorn. The
Python-based load generator is the bottleneck, so treat these numbers as a
relative sanity check rather than a rigorous benchmark.

## Testing

```bash
pytest -q
```

The suite covers routing, typed path/query/header parameters, JSON and Pydantic
bodies, dataclasses, sync and async handlers, response classes, exceptions,
OpenAPI/docs, routers, lifecycle hooks and request limits.

## How it works

The Python layer performs signature introspection once at registration time
and hands a compact route specification to the Rust core. At request time the
Rust server parses and routes the request, builds typed Python arguments, and
calls the handler. Response serialization (dict/list → JSON) also happens in
Rust via `pythonize` + `serde_json`.

## Limits

- One body parameter per handler.
- Custom exception handlers run synchronously.
- No dependency injection (`Depends`) yet.
- No built-in WebSocket support.
- Pydantic is optional; without it, use dataclasses or plain dicts.

## License

MIT
