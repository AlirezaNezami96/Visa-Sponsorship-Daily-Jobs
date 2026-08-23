"""Apify Actor package with transparent integration of the official Apify SDK."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

# Find real site-packages apify module
_this_dir = Path(__file__).resolve().parent
_real_apify_init = None

for p in sys.path:
    if not p or p in (".", ""):
        continue
    try:
        resolved = Path(p).resolve()
        if resolved == _this_dir or resolved == _this_dir.parent:
            continue
        candidate = resolved / "apify" / "__init__.py"
        if candidate.exists():
            _real_apify_init = candidate
            break
    except Exception:
        continue

if _real_apify_init:
    # Ensure site-packages apify directory is in __path__ so submodules (e.g. storage_clients) resolve
    _sdk_dir = str(_real_apify_init.parent)
    if _sdk_dir not in __path__:
        __path__.append(_sdk_dir)

    # Read and exec the real apify/__init__.py in our namespace
    with open(_real_apify_init, "r", encoding="utf-8") as f:
        _code = compile(f.read(), str(_real_apify_init), "exec")
        exec(_code, globals())

# Re-export Actor and local modules
from apify.config_mapper import input_to_config
from apify.sink import ApifyDatasetSink

__all__ = [
    "Actor",
    "input_to_config",
    "ApifyDatasetSink",
]
