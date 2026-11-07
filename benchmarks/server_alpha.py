"""Benchmark server implemented with AlphaAPI."""
from __future__ import annotations

import os

from alphaapi import Alpha

app = Alpha(docs=False)


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
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        workers=int(os.environ["WORKERS"]) if os.environ.get("WORKERS") else None,
        access_log=False,
    )
