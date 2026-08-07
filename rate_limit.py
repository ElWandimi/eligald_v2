"""
rate_limit.py - In-memory rate limiter for Eligald.
"""
import time
from collections import defaultdict
from threading import Lock
from flask import request, jsonify

_store = defaultdict(list)
_lock  = Lock()

def check_rate_limit(action, limit=10, window=60):
    ip  = request.remote_addr or "unknown"
    key = f"{ip}:{action}"
    now = time.time()
    with _lock:
        _store[key] = [t for t in _store[key] if now - t < window]
        if len(_store[key]) >= limit:
            return False
        _store[key].append(now)
        return True

def rate_limit_response(action="this action"):
    return jsonify({"success": False, "error": f"Too many requests. Please wait and try again."}), 429
