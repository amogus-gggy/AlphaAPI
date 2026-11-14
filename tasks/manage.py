#!/usr/bin/env python
"""Manage the tasks AlphaAPI project."""
from __future__ import annotations

import sys

from alphaapi.cli import main

if __name__ == "__main__":
    main(["runserver", "tasks.app:app", *sys.argv[1:]])
