#!/usr/bin/env python
"""Manage the test AlphaAPI project."""
from __future__ import annotations

import sys

from alphaapi.cli import main

if __name__ == "__main__":
    main(["runserver", "test.app:app", *sys.argv[1:]])
