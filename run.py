#!/usr/bin/env python3
"""
qd3_fsutils — File System Utilities MCP Server

Run the MCP server:
    python3 run.py

Or install as a module:
    pip install -e .
    python3 -m qd3_fsutils.server
"""

import sys
import os

# Ensure the package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qd3_fsutils.server import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
