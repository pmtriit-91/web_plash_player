#!/usr/bin/env python3
"""Backward-compatible entry point for split Core integrity verification."""

import json
import sys

from agent_os_lifecycle import verify_core


if __name__ == "__main__":
    result = verify_core()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("ok") else 2)
