# -*- coding: utf-8 -*-
"""Compatibility facade for the CLI inspector.

The authoritative query inspection implementation lives in deep_inspector.py.
This module intentionally contains no duplicate retrieval or rendering logic.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from deep_inspector import render_query_trace

_INSPECT_COMMANDS = {"inspect", "deep", "deep inspect", "inspect memory", "debug memory"}


def render_detailed_inspection(
    brain: Any,
    trace: Optional[Dict[str, Any]] = None,
    *,
    source: str = "cli",
    query: Optional[str] = None,
    response: Optional[str] = None,
) -> None:
    """Backward-compatible entry point; delegates to deep_inspector only."""
    command = (query or "").strip().lower()
    if command in _INSPECT_COMMANDS:
        render_query_trace(
            brain,
            trace,
            source=source,
            query=query,
            response=response,
        )
