"""
csrf.py – Lightweight CSRF protection using per-session tokens.
Exempts GET/HEAD/OPTIONS and specific paths that POST before a session exists.
"""
import hmac
import secrets
from flask import session, request, abort

# Paths that legitimately POST without a prior GET (no token in session yet)
EXEMPT_PATHS = {"/admin/login", "/contact"}


def generate_csrf_token():
    """Generate a token for this session (idempotent)."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf():
    """Validate CSRF token on all state-changing requests."""
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    if request.path in EXEMPT_PATHS:
        return
    token    = (request.form.get("csrf_token")
                or request.headers.get("X-CSRF-Token"))
    expected = session.get("csrf_token")
    if not token or not expected or not hmac.compare_digest(token, expected):
        abort(400, "Session expired or invalid request. Please go back and try again.")
