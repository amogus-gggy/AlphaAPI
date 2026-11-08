"""Example: run FastAPI-style code on AlphaAPI's Rust core.

Run with:
    python examples/fastapi_compat.py
    # or
    uvicorn examples.fastapi_compat:app --port 8000
"""

import alphaapi.compat.fastapi as compat

# This emits a CompatibilityWarning on purpose: compatibility mode can degrade
# performance and is not a perfect FastAPI replacement.
compat.install()

from fastapi import Depends, FastAPI, Header, HTTPException, Query  # noqa: E402

app = FastAPI(title="AlphaAPI FastAPI-compat demo", version="0.1.0")


def get_token(x_token: str = Header(default="anonymous")) -> str:
    if x_token == "forbidden":
        raise HTTPException(status_code=403, detail="Forbidden")
    return x_token


@app.get("/items/{item_id}")
def read_item(
    item_id: int,
    q: str | None = Query(default=None, description="Search query"),
    token: str = Depends(get_token),
):
    return {"item_id": item_id, "q": q, "token": token}


@app.post("/items", status_code=201)
def create_item(payload: dict):
    return {"created": payload}


if __name__ == "__main__":
    app.run(port=8000)
