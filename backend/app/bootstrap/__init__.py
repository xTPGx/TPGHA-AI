"""Startup bootstrap package (PART 2/3).

Self-initializes the orchestrator on launch: ensures config exists, connects to
Home Assistant, runs the initial discovery scan, and keeps itself current with a
periodic background scan. Never crashes the process on failure; it degrades.
"""
from .startup import (  # noqa: F401
    AppState,
    bootstrap,
    get_app_state,
    periodic_scan_loop,
)
