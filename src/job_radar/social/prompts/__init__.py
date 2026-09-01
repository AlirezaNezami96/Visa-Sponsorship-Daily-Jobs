"""Isolated per-platform prompt definitions and template formatting helpers.

Each platform module owns its own system prompt and user prompt formatting logic.
No platform template branches into or shares text with another platform.
"""
from __future__ import annotations
