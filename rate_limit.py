"""
rate_limit.py – Simple in-memory rate limiter.
Uses a sliding window per (IP, action) key.
No external dependencies required.
"""
import time
from collections import defaultdict
from threading import Lock
from flask import request, jsonify

_store: dict = defaultdict(list)  # key -> list of timestamps
_lock  = Lock()


def _clean(timestamps: list, window: float) -> list:
    now = time.time()
    return [t for t in timestamps if now - t < window]


def check_rate_limit(action: str, limit: int = 10, window: int = 60) -> bool:
    """
    Returns True if request is allowed, False if rate-limited.
    action  – logical name (e.g. 'login', 'contact')
    limit   – max requests per window
    window  – window size in seconds
    """
    ip  = request.remote_addr or "unknown"
    key = f"{ip}:{action}"
    with _lock:
        _store[key] = _clean(_store[key], window)
        if len(_store[key]) >= limit:
            return False
        _store[key].append(time.time())
        return True


def rate_limit_response(action: str = "this action"):
    """Return a 429 JSON response."""
    return jsonify({
        "success": False,
        "error": f"Too many requests for {action}. Please wait a moment and try again."
    }), 429


def purge_old_entries():
    """Call periodically to free memory (optional)."""
    with _lock:
        now = time.time()
        for key in list(_store.keys()):
            _store[key] = [t for t in _store[key] if now - t < 3600]
            if not _store[key]:
                del _store[key]
