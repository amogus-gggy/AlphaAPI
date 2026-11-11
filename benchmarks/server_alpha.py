"""Benchmark server implemented with AlphaAPI."""
from __future__ import annotations

import os

from alphaapi import Application, JsonResponse, path


def json_endpoint(request):
    return JsonResponse({"message": "Hello, World!", "number": 42, "ok": True})


def plaintext_endpoint(request):
    return "Hello, World!"


def item_endpoint(request, item_id: int):
    return JsonResponse({"item_id": item_id, "name": f"item-{item_id}"})


urlpatterns = [
    path("/json", json_endpoint),
    path("/plaintext", plaintext_endpoint),
    path("/items/<int:item_id>", item_endpoint),
]

app = Application(urlpatterns=urlpatterns)


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        workers=int(os.environ["WORKERS"]) if os.environ.get("WORKERS") else None,
        access_log=False,
    )
