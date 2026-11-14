"""Application entry point."""
from __future__ import annotations

from alphaapi import Application

app = Application(settings_module=f"{__package__}.settings")
