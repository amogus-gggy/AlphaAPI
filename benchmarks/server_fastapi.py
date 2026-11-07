"""Benchmark server implemented with FastAPI (plus uvicorn)."""
from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/json")
def json_endpoint():
    return {"message": "Hello, World!", "number": 42, "ok": True}


@app.get("/plaintext")
def plaintext_endpoint():
    return "Hello, World!"


@app.get("/items/{item_id}")
def item_endpoint(item_id: int):
    return {"item_id": item_id, "name": f"item-{item_id}"}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        log_level="warning",
        access_log=False,
    )
