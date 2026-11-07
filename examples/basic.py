"""A small example application.

Run with:
    python examples/basic.py
or:
    alphaapi run examples.basic:app --reload
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from alphaapi import (
    Alpha,
    Body,
    Header,
    HTTPException,
    JSONResponse,
    Query,
    Request,
)

app = Alpha(
    title="AlphaAPI example",
    version="1.0.0",
    description="A tiny demo of the AlphaAPI framework.",
)


@dataclass
class Item:
    name: str
    price: float
    tags: list[str] | None = None


@app.on_startup
def startup() -> None:
    print("starting up")


@app.on_shutdown
def shutdown() -> None:
    print("shutting down")


@app.get("/", tags=["misc"])
def root() -> dict[str, str]:
    return {"message": "Hello from AlphaAPI"}


@app.get("/items/{item_id}", tags=["items"])
def read_item(
    item_id: int,
    q: str | None = None,
    limit: int = Query(10, description="Maximum number of results"),
) -> dict[str, object]:
    return {"item_id": item_id, "q": q, "limit": limit}


@app.post("/items", status_code=201, tags=["items"])
def create_item(item: Item) -> dict[str, object]:
    return {"created": item}


@app.get("/async", tags=["misc"])
async def async_handler() -> dict[str, bool]:
    await asyncio.sleep(0.01)
    return {"async": True}


@app.get("/request-info", tags=["misc"])
def request_info(request: Request) -> dict[str, object]:
    return {
        "method": request.method,
        "path": request.path,
        "client": request.client,
        "user_agent": request.header("user-agent"),
    }


@app.get("/text", tags=["misc"])
def plain_text() -> str:
    return "just some text"


@app.get("/custom-response", include_in_schema=False)
def custom_response() -> JSONResponse:
    return JSONResponse({"custom": True}, status_code=202, headers={"x-demo": "yes"})


@app.get("/teapot", tags=["misc"])
def teapot() -> None:
    raise HTTPException(status_code=418, detail="I'm a teapot")


@app.get("/headers", tags=["misc"])
def header_demo(x_token: str = Header(...)) -> dict[str, str]:
    return {"x_token": x_token}


@app.post("/echo", tags=["misc"])
def echo(payload: dict = Body(...)) -> dict:
    return payload


if __name__ == "__main__":
    app.run(port=8000, access_log=True)
