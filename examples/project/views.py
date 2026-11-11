"""Example views."""
from __future__ import annotations

from alphaapi import HttpResponse, JsonResponse, View


async def index(request):
    return JsonResponse({"message": "Hello from the example project"})


async def item(request, item_id: int):
    return JsonResponse(
        {
            "item_id": item_id,
            "query": request.GET.dict(),
            "reverse_example": request.path,
        }
    )


class ItemDetailView(View):
    async def get(self, request, item_id: int):
        return JsonResponse({"item_id": item_id, "method": "GET"})

    async def put(self, request, item_id: int):
        return JsonResponse({"item_id": item_id, "payload": request.json()})


async def health(request):
    if request.GET.get("strict") == "1":
        raise RuntimeError("strict health check failed")
    return HttpResponse("ok", content_type="text/plain; charset=utf-8")
