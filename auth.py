"""
auth.py – Session-based authentication helpers.
"""
import functools
from flask import session, redirect, url_for, flash, g
from database import get_db

def load_current_user():
    user_id = session.get("user_id")
    if user_id:
        db   = get_db()
        user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        db.close()
        g.user = dict(user) if user else None
    else:
        g.user = None

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not g.get("user"):
            flash("Please log in to access the admin panel.", "warning")
            return redirect(url_for("admin_bp.login"))
        return f(*args, **kwargs)
    return decorated

def super_admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        user = g.get("user")
        if not user:
            flash("Please log in.", "warning")
            return redirect(url_for("admin_bp.login"))
        if user["role"] != "super_admin":
            flash("Super Admin access required.", "danger")
            return redirect(url_for("admin_bp.dashboard"))
        return f(*args, **kwargs)
    return decorated

def login_user(user_id):
    session.clear()
    session["user_id"]  = user_id
    session.permanent   = True

def logout_user():
    session.clear()
