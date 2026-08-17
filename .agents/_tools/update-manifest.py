#!/usr/bin/env python3
"""Compatibility wrapper for explicit Agent OS base-manifest generation."""

import os
import sys
from pathlib import Path


if __name__ == "__main__":
    lifecycle = Path(__file__).with_name("agent_os_lifecycle.py")
    os.execv(
        sys.executable,
        [sys.executable, str(lifecycle), "build-manifest", *sys.argv[1:]],
    )
