"""A single-file AlphaAPI project.

Run with:
    python examples/basic.py
or:
    alphaapi runserver examples.basic:app --reload
"""
from __future__ import annotations

import asyncio

from alphaapi import (
    Application,
    HTTPException,
    HttpResponse,
    JsonResponse,
    View,
    include,
    path,
    settings,
)

settings.configure(
    DEBUG=True,
    TITLE="AlphaAPI example",
    VERSION="1.0.0",
)


async def index(request):
    return JsonResponse({"message": "Hello from AlphaAPI"})


async def read_item(request, item_id: int):
    return JsonResponse(
        {
            "item_id": item_id,
            "q": request.GET.get("q"),
            "limit": int(request.GET.get("limit", 10)),
        }
    )


async def create_item(request):
    payload = request.json()
    return JsonResponse({"created": payload}, status=201)


async def async_handler(request):
    await asyncio.sleep(0.01)
    return JsonResponse({"async": True})


async def request_info(request):
    return JsonResponse(
        {
            "method": request.method,
            "path": request.path,
            "client": request.client,
            "user_agent": request.headers.get("user-agent"),
        }
    )


async def plain_text(request):
    return HttpResponse("just some text", content_type="text/plain; charset=utf-8")


async def teapot(request):
    raise HTTPException(status_code=418, detail="I'm a teapot")


async def echo(request):
    return JsonResponse(request.json())


class ItemView(View):
    """A class-based view using async methods."""

    async def get(self, request, item_id: int):
        return JsonResponse({"item_id": item_id, "view": "class"})

    async def post(self, request, item_id: int):
        return JsonResponse({"item_id": item_id, "payload": request.json()}, status=201)


api_patterns = [
    path("ping/", lambda request: JsonResponse({"pong": True}), name="ping"),
]

urlpatterns = [
    path("", index, name="index"),
    path("items/<int:item_id>/", read_item, name="item"),
    path("items/<int:item_id>/class/", ItemView.as_view(), name="item-class"),
    path("items/", create_item, name="create-item"),
    path("async/", async_handler, name="async"),
    path("request-info/", request_info, name="request-info"),
    path("text/", plain_text, name="text"),
    path("teapot/", teapot, name="teapot"),
    path("echo/", echo, name="echo"),
    path("api/", include((api_patterns, "api"))),
]

app = Application(urlpatterns=urlpatterns)


if __name__ == "__main__":
    app.run(port=8000, access_log=True)
