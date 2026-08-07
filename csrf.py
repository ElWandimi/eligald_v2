"""
csrf.py - CSRF protection for Eligald.
"""
import hmac, secrets
from flask import session, request, abort

EXEMPT_PATHS = {"/admin/login", "/contact"}

def generate_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]

def validate_csrf():
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    if request.path in EXEMPT_PATHS:
        return
    token    = (request.form.get("csrf_token") or request.headers.get("X-CSRF-Token"))
    expected = session.get("csrf_token")
    if not token or not expected or not hmac.compare_digest(token, expected):
        abort(400, "Session expired. Please go back and try again.")
