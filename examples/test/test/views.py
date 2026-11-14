"""Views for the test project."""
from __future__ import annotations

from alphaapi import HttpResponse
from alphaapi.welcome import welcome_page


async def index(request):
    return HttpResponse(welcome_page("test"))


async def health(request):
    return HttpResponse("ok", content_type="text/plain; charset=utf-8")
