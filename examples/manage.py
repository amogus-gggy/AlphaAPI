#!/usr/bin/env python
"""Tiny manage.py-style runner for the example project.

Run from the ``examples`` directory:

    python manage.py --port 8000
"""
from __future__ import annotations

import sys

from alphaapi.cli import main

if __name__ == "__main__":
    main(["runserver", "project.app:app", *sys.argv[1:]])
