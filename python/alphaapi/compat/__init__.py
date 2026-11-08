"""Compatibility layers for AlphaAPI.

WARNING: Compatibility layers monkeypatch third-party modules and trade
correctness/performance for API familiarity. They may degrade performance, may
not be optimal, and may not support all features or edge cases. Prefer native
AlphaAPI APIs for production use.
"""

from .fastapi import install_fastapi_compat

__all__ = ["install_fastapi_compat"]
