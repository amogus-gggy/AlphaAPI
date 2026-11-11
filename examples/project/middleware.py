"""Example async middleware."""
from __future__ import annotations

import time


class TimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    async def __call__(self, request):
        started = time.perf_counter()
        response = await self.get_response(request)
        elapsed = time.perf_counter() - started
        response["X-Elapsed-Ms"] = f"{elapsed * 1000:.2f}"
        return response
