"""
blueprints/admin.py – Full admin panel for Eligald Industrial Chemicals.
Routes: login, dashboard, products, leads, orders, tickets,
        notifications, settings, users, activity log, PDF invoice,
        CSV export, DB backup.
"""

import os, csv, io, json, secrets
from datetime import datetime, date, timedelta
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, g, flash, jsonify, send_file, abort, current_app
)
from werkzeug.security  import generate_password_hash, check_password_hash
from werkzeug.utils     import secure_filename

from database import (
    get_db, db_conn, next_invoice_number,
    notify_all_admins, notify_user, log_action, DB_PATH
)
from auth import login_user, logout_user, login_required, super_admin_required
from pdf_generator import generate_invoice_pdf
from rate_limit import check_rate_limit

admin_bp = Blueprint("admin_bp", __name__, template_folder="../templates/admin")

ALLOWED = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED


def save_upload(file, subfolder):
    fn  = secure_filename(file.filename)
    ext = fn.rsplit(".", 1)[-1].lower()
    unique = f"{secrets.token_hex(8)}.{ext}"
    dest = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder, unique)
    file.save(dest)
    return f"/static/uploads/{subfolder}/{unique}"


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN / LOGOUT
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(url_for("admin_bp.dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not check_rate_limit("login", limit=10, window=900):
            error = "Too many login attempts. Please wait 15 minutes and try again."
            return render_template("admin/login.html", error=error)
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        db.close()
        if user and check_password_hash(user["password_hash"], password):
            # Two-factor via WhatsApp
            if user["two_factor_enabled"] and user["whatsapp_number"]:
                settings_row = get_db().execute("SELECT * FROM site_settings WHERE id=1").fetchone()
                s = dict(settings_row) if settings_row else {}
                if not (s.get("wa_business_token") and s.get("wa_phone_id")):
                    error = "Two-factor authentication is enabled but WhatsApp Business API is not configured. Contact your Super Admin."
                    return render_template("admin/login.html", error=error)
                otp = f"{secrets.randbelow(1000000):06d}"
                expires = (datetime.now() + timedelta(minutes=5)).isoformat()
                with db_conn() as conn:
                    conn.execute(
                        "UPDATE users SET otp_code=?, otp_expires=?, otp_purpose='login' WHERE id=?",
                        (generate_password_hash(otp), expires, user["id"])
                    )
                try:
                    _send_whatsapp(
                        user["whatsapp_number"],
                        f"Your Eligald Admin login code is: {otp}\n\nThis code expires in 5 minutes. "
                        f"Do not share it with anyone.",
                        s
                    )
                except Exception as e:
                    error = f"Could not send WhatsApp code: {e}"
                    return render_template("admin/login.html", error=error)
                session["pending_2fa_user_id"] = user["id"]
                session["pending_2fa_purpose"] = "login"
                return redirect(url_for("admin_bp.verify_otp"))

            # No 2FA — log in directly
            login_user(user["id"])
            log_action(user["id"], user["username"], "LOGIN", "Admin login")
            if user["must_change_pw"]:
                flash("Please change your password before continuing.", "warning")
                return redirect(url_for("admin_bp.change_password"))
            return redirect(url_for("admin_bp.dashboard"))
        error = "Invalid username or password."
    return render_template("admin/login.html", error=error)


@admin_bp.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("pending_2fa_user_id")
    purpose = session.get("pending_2fa_purpose", "login")
    if not uid:
        return redirect(url_for("admin_bp.login"))

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    db.close()
    if not user:
        session.pop("pending_2fa_user_id", None)
        return redirect(url_for("admin_bp.login"))

    error = None
    masked_number = ""
    if user["whatsapp_number"]:
        num = user["whatsapp_number"]
        masked_number = f"•••{num[-4:]}" if len(num) >= 4 else "••••"

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if not check_rate_limit("verify_otp", limit=8, window=600):
            error = "Too many attempts. Please wait 10 minutes."
            return render_template("admin/verify_otp.html", error=error, masked_number=masked_number, purpose=purpose)

        valid = False
        if user["otp_code"] and user["otp_expires"]:
            try:
                not_expired = datetime.now() < datetime.fromisoformat(user["otp_expires"])
                code_matches = check_password_hash(user["otp_code"], code)
                valid = not_expired and code_matches and user["otp_purpose"] == purpose
            except Exception:
                valid = False

        if not valid:
            error = "Invalid or expired code. Please try again or resend a new code."
            return render_template("admin/verify_otp.html", error=error, masked_number=masked_number, purpose=purpose)

        # Success — clear OTP
        with db_conn() as conn:
            conn.execute("UPDATE users SET otp_code='', otp_expires='', otp_purpose='' WHERE id=?", (uid,))
        session.pop("pending_2fa_user_id", None)
        session.pop("pending_2fa_purpose", None)

        if purpose == "login":
            login_user(uid)
            log_action(uid, user["username"], "LOGIN", "Admin login (WhatsApp 2FA verified)")
            if user["must_change_pw"]:
                flash("Please change your password before continuing.", "warning")
                return redirect(url_for("admin_bp.change_password"))
            return redirect(url_for("admin_bp.dashboard"))
        elif purpose == "reset":
            session["otp_reset_user_id"] = uid
            return redirect(url_for("admin_bp.reset_password_otp"))

    return render_template("admin/verify_otp.html", error=error, masked_number=masked_number, purpose=purpose)


@admin_bp.route("/verify-otp/resend", methods=["POST"])
def resend_otp():
    uid = session.get("pending_2fa_user_id")
    purpose = session.get("pending_2fa_purpose", "login")
    if not uid:
        return redirect(url_for("admin_bp.login"))
    if not check_rate_limit("resend_otp", limit=3, window=600):
        flash("Too many resend requests. Please wait before trying again.", "danger")
        return redirect(url_for("admin_bp.verify_otp"))

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    settings_row = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    db.close()
    s = dict(settings_row) if settings_row else {}

    if user and user["whatsapp_number"]:
        otp = f"{secrets.randbelow(1000000):06d}"
        expires = (datetime.now() + timedelta(minutes=5)).isoformat()
        with db_conn() as conn:
            conn.execute(
                "UPDATE users SET otp_code=?, otp_expires=?, otp_purpose=? WHERE id=?",
                (generate_password_hash(otp), expires, purpose, uid)
            )
        try:
            _send_whatsapp(
                user["whatsapp_number"],
                f"Your new Eligald Admin verification code is: {otp}\n\nThis code expires in 5 minutes.",
                s
            )
            flash("A new code has been sent via WhatsApp.", "success")
        except Exception as e:
            flash(f"Could not resend code: {e}", "danger")
    return redirect(url_for("admin_bp.verify_otp"))


@admin_bp.route("/logout")
def logout():
    if g.get("user"):
        log_action(g.user["id"], g.user["username"], "LOGOUT")
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("admin_bp.login"))


@admin_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    message = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        method   = request.form.get("method", "email")
        if not check_rate_limit("forgot_password", limit=5, window=900):
            return render_template("admin/forgot_password.html",
                                   message="Too many requests. Please wait 15 minutes.")
        db   = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        settings_row = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
        db.close()
        s = dict(settings_row) if settings_row else {}

        if method == "whatsapp":
            message = "If that account exists and has a WhatsApp number on file, a verification code has been sent."
            if user and user["whatsapp_number"]:
                if not (s.get("wa_business_token") and s.get("wa_phone_id")):
                    message = "WhatsApp reset is not available right now. Please try email reset instead."
                else:
                    otp = f"{secrets.randbelow(1000000):06d}"
                    expires = (datetime.now() + timedelta(minutes=10)).isoformat()
                    with db_conn() as conn:
                        conn.execute(
                            "UPDATE users SET otp_code=?, otp_expires=?, otp_purpose='reset' WHERE id=?",
                            (generate_password_hash(otp), expires, user["id"])
                        )
                    try:
                        _send_whatsapp(
                            user["whatsapp_number"],
                            f"Your Eligald Admin password reset code is: {otp}\n\n"
                            f"This code expires in 10 minutes. Do not share it with anyone.",
                            s
                        )
                        session["pending_2fa_user_id"] = user["id"]
                        session["pending_2fa_purpose"]  = "reset"
                        return redirect(url_for("admin_bp.verify_otp"))
                    except Exception as e:
                        print(f"[FORGOT-PASSWORD] WhatsApp send failed: {e}")
        else:
            # Always show the same message whether or not the user exists (avoid username enumeration)
            message = "If that account exists and has an email on file, a reset link has been sent."
            if user and user["email"]:
                token   = secrets.token_urlsafe(32)
                expires = (datetime.now() + timedelta(hours=1)).isoformat()
                with db_conn() as conn:
                    conn.execute(
                        "UPDATE users SET reset_token=?, reset_token_expires=? WHERE id=?",
                        (token, expires, user["id"])
                    )
                reset_url = url_for("admin_bp.reset_password", token=token, _external=True)
                try:
                    _send_email(
                        user["email"],
                        "Eligald Admin — Password Reset Request",
                        f"You requested a password reset for the Eligald admin panel.\n\n"
                        f"Click the link below to set a new password (valid for 1 hour):\n{reset_url}\n\n"
                        f"If you didn't request this, you can safely ignore this email.",
                        s
                    )
                except Exception as e:
                    print(f"[FORGOT-PASSWORD] Email send failed: {e}")
    return render_template("admin/forgot_password.html", message=message)


@admin_bp.route("/reset-password-otp", methods=["GET", "POST"])
def reset_password_otp():
    uid = session.get("otp_reset_user_id")
    if not uid:
        return redirect(url_for("admin_bp.forgot_password"))
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    db.close()
    if not user:
        session.pop("otp_reset_user_id", None)
        return redirect(url_for("admin_bp.forgot_password"))

    error = None
    if request.method == "POST":
        new_pw  = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if new_pw != confirm:
            error = "Passwords do not match."
        elif len(new_pw) < 8:
            error = "Password must be at least 8 characters."
        else:
            with db_conn() as conn:
                conn.execute(
                    "UPDATE users SET password_hash=?, must_change_pw=0 WHERE id=?",
                    (generate_password_hash(new_pw), uid)
                )
            log_action(uid, user["username"], "PASSWORD_RESET", "Reset via WhatsApp OTP")
            session.pop("otp_reset_user_id", None)
            flash("Password updated. You can now log in.", "success")
            return redirect(url_for("admin_bp.login"))
    return render_template("admin/reset_password.html", error=error, token=None, via_whatsapp=True)


@admin_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    db   = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE reset_token=? AND reset_token_expires!=''", (token,)
    ).fetchone()
    db.close()
    valid = False
    if user:
        try:
            expires = datetime.fromisoformat(user["reset_token_expires"])
            valid = datetime.now() < expires
        except Exception:
            valid = False
    if not valid:
        flash("This reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for("admin_bp.forgot_password"))

    error = None
    if request.method == "POST":
        new_pw  = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if new_pw != confirm:
            error = "Passwords do not match."
        elif len(new_pw) < 8:
            error = "Password must be at least 8 characters."
        else:
            with db_conn() as conn:
                conn.execute(
                    "UPDATE users SET password_hash=?, must_change_pw=0, reset_token='', reset_token_expires='' WHERE id=?",
                    (generate_password_hash(new_pw), user["id"])
                )
            log_action(user["id"], user["username"], "PASSWORD_RESET", "Reset via email link")
            flash("Password updated. You can now log in.", "success")
            return redirect(url_for("admin_bp.login"))
    return render_template("admin/reset_password.html", error=error, token=token)


@admin_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    error = None
    if request.method == "POST":
        current  = request.form.get("current_password", "")
        new_pw   = request.form.get("new_password", "")
        confirm  = request.form.get("confirm_password", "")
        if new_pw != confirm:
            error = "New passwords do not match."
        elif len(new_pw) < 8:
            error = "Password must be at least 8 characters."
        else:
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
            db.close()
            if not check_password_hash(user["password_hash"], current):
                error = "Current password is incorrect."
            else:
                with db_conn() as conn:
                    conn.execute(
                        "UPDATE users SET password_hash=?, must_change_pw=0 WHERE id=?",
                        (generate_password_hash(new_pw), g.user["id"])
                    )
                log_action(g.user["id"], g.user["username"], "CHANGE_PASSWORD")
                flash("Password updated successfully.", "success")
                return redirect(url_for("admin_bp.dashboard"))
    return render_template("admin/change_password.html", error=error)


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/")
@login_required
def dashboard():
    db = get_db()
    total_products  = db.execute("SELECT COUNT(*) FROM products WHERE is_active=1").fetchone()[0]
    pending_orders  = db.execute("SELECT COUNT(*) FROM orders WHERE status IN ('draft','sent')").fetchone()[0]
    open_tickets    = db.execute("SELECT COUNT(*) FROM tickets WHERE status!='closed'").fetchone()[0]
    unread_notifs   = db.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
        (g.user["id"],)
    ).fetchone()[0]

    recent_leads   = db.execute(
        "SELECT l.*, p.name AS product_name FROM leads l "
        "LEFT JOIN products p ON l.product_id=p.id "
        "ORDER BY l.created_at DESC LIMIT 6"
    ).fetchall()
    recent_tickets = db.execute(
        "SELECT * FROM tickets ORDER BY created_at DESC LIMIT 6"
    ).fetchall()

    # Chart data: orders by status
    order_stats = db.execute(
        "SELECT status, COUNT(*) as cnt FROM orders GROUP BY status"
    ).fetchall()
    chart_labels = [r["status"].title() for r in order_stats]
    chart_data   = [r["cnt"] for r in order_stats]

    # Leads per month (last 6 months)
    leads_monthly = db.execute("""
        SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as cnt
        FROM leads
        WHERE created_at >= date('now','-6 months')
        GROUP BY month ORDER BY month
    """).fetchall()
    lead_months = [r["month"] for r in leads_monthly]
    lead_counts = [r["cnt"]   for r in leads_monthly]

    db.close()
    return render_template("admin/dashboard.html",
        total_products=total_products, pending_orders=pending_orders,
        open_tickets=open_tickets, unread_notifs=unread_notifs,
        recent_leads=recent_leads, recent_tickets=recent_tickets,
        chart_labels=json.dumps(chart_labels), chart_data=json.dumps(chart_data),
        lead_months=json.dumps(lead_months),   lead_counts=json.dumps(lead_counts),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTS
# ─────────────────────────────────────────────────────────────────────────────

CATEGORIES = ["Industrial Solvents", "Acids & Bases", "Specialty Chemicals", "Laboratory Reagents"]


@admin_bp.route("/products")
@login_required
def products():
    db  = get_db()
    q   = request.args.get("q", "").strip()
    cat = request.args.get("category", "All")
    query = "SELECT * FROM products WHERE 1=1"
    params = []
    if q:
        query += " AND (name LIKE ? OR description LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if cat != "All":
        query += " AND category=?"
        params.append(cat)
    query += " ORDER BY name"
    prods = db.execute(query, params).fetchall()
    db_cats = [r["name"] for r in db.execute(
        "SELECT name FROM categories WHERE is_active=1 ORDER BY sort_order,name"
    ).fetchall()] or CATEGORIES
    db.close()
    return render_template("admin/products.html",
        products=prods, categories=db_cats, q=q, active_cat=cat)


@admin_bp.route("/products/new", methods=["GET", "POST"])
@login_required
def product_new():
    if request.method == "POST":
        name    = request.form.get("name", "").strip()
        desc    = request.form.get("description", "").strip()
        specs   = request.form.get("specifications", "").strip()
        cat     = request.form.get("category", "Specialty Chemicals")
        price   = request.form.get("price_per_unit", "") or None
        stock   = request.form.get("stock_quantity", "").strip()
        stock   = int(stock) if stock else None
        low_thr = request.form.get("low_stock_threshold", "10").strip()
        low_thr = int(low_thr) if low_thr else 10
        active  = 1 if request.form.get("is_active") else 0
        img_url = request.form.get("image_url", "").strip()

        if "image_file" in request.files:
            f = request.files["image_file"]
            if f and f.filename and allowed_file(f.filename):
                img_url = save_upload(f, "products")

        _cats = [r["name"] for r in get_db().execute(
            "SELECT name FROM categories WHERE is_active=1 ORDER BY sort_order,name"
        ).fetchall()] or CATEGORIES

        if not name:
            flash("Product name is required.", "danger")
            return render_template("admin/product_form.html", product=None, categories=_cats)

        with db_conn() as conn:
            cur = conn.execute(
                "INSERT INTO products (name,description,specifications,image_url,category,price_per_unit,stock_quantity,low_stock_threshold,is_active) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (name, desc, specs, img_url, cat, price, stock, low_thr, active)
            )
            pid = cur.lastrowid
        log_action(g.user["id"], g.user["username"], "PRODUCT_CREATE", f"Created product #{pid}: {name}")
        flash(f"Product '{name}' created.", "success")
        return redirect(url_for("admin_bp.products"))

    _cats = [r["name"] for r in get_db().execute(
        "SELECT name FROM categories WHERE is_active=1 ORDER BY sort_order,name"
    ).fetchall()] or CATEGORIES
    return render_template("admin/product_form.html", product=None, categories=_cats)


@admin_bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def product_edit(pid):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    db.close()
    if not product:
        abort(404)

    if request.method == "POST":
        name    = request.form.get("name", "").strip()
        desc    = request.form.get("description", "").strip()
        specs   = request.form.get("specifications", "").strip()
        cat     = request.form.get("category", "Specialty Chemicals")
        price   = request.form.get("price_per_unit", "") or None
        stock   = request.form.get("stock_quantity", "").strip()
        stock   = int(stock) if stock else None
        low_thr = request.form.get("low_stock_threshold", "10").strip()
        low_thr = int(low_thr) if low_thr else 10
        active  = 1 if request.form.get("is_active") else 0
        img_url = request.form.get("image_url", product["image_url"])

        if "image_file" in request.files:
            f = request.files["image_file"]
            if f and f.filename and allowed_file(f.filename):
                img_url = save_upload(f, "products")

        with db_conn() as conn:
            conn.execute(
                "UPDATE products SET name=?,description=?,specifications=?,image_url=?,"
                "category=?,price_per_unit=?,stock_quantity=?,low_stock_threshold=?,is_active=?,updated_at=datetime('now') WHERE id=?",
                (name, desc, specs, img_url, cat, price, stock, low_thr, active, pid)
            )
        log_action(g.user["id"], g.user["username"], "PRODUCT_EDIT", f"Edited product #{pid}: {name}")
        flash(f"Product '{name}' updated.", "success")
        return redirect(url_for("admin_bp.products"))

    _cats = [r["name"] for r in get_db().execute("SELECT name FROM categories WHERE is_active=1 ORDER BY sort_order,name").fetchall()] or CATEGORIES
    return render_template("admin/product_form.html", product=dict(product), categories=_cats)


@admin_bp.route("/products/<int:pid>/delete", methods=["POST"])
@login_required
def product_delete(pid):
    db = get_db()
    p = db.execute("SELECT name FROM products WHERE id=?", (pid,)).fetchone()
    db.close()
    if p:
        with db_conn() as conn:
            conn.execute("DELETE FROM products WHERE id=?", (pid,))
        log_action(g.user["id"], g.user["username"], "PRODUCT_DELETE", f"Deleted product #{pid}: {p['name']}")
        flash(f"Product '{p['name']}' deleted.", "success")
    return redirect(url_for("admin_bp.products"))


@admin_bp.route("/products/<int:pid>/toggle", methods=["POST"])
@login_required
def product_toggle(pid):
    with db_conn() as conn:
        conn.execute(
            "UPDATE products SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
            (pid,)
        )
    return redirect(url_for("admin_bp.products"))


# ─────────────────────────────────────────────────────────────────────────────
# LEADS
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/leads")
@login_required
def leads():
    db     = get_db()
    status = request.args.get("status", "All")
    q      = request.args.get("q", "").strip()
    query  = ("SELECT l.*, p.name AS product_name FROM leads l "
              "LEFT JOIN products p ON l.product_id=p.id WHERE 1=1")
    params = []
    if status != "All":
        query += " AND l.status=?"
        params.append(status)
    if q:
        query += " AND (l.customer_name LIKE ? OR l.phone_number LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    query += " ORDER BY l.created_at DESC"
    all_leads = db.execute(query, params).fetchall()
    products  = db.execute("SELECT id,name FROM products WHERE is_active=1 ORDER BY name").fetchall()
    db.close()
    return render_template("admin/leads.html", leads=all_leads,
                           products=products, active_status=status, q=q)


@admin_bp.route("/leads/new", methods=["GET", "POST"])
@login_required
def lead_new():
    db = get_db()
    products = db.execute("SELECT id,name FROM products WHERE is_active=1 ORDER BY name").fetchall()
    db.close()
    if request.method == "POST":
        cname  = request.form.get("customer_name", "").strip()
        phone  = request.form.get("phone_number",  "").strip()
        email  = request.form.get("email",         "").strip()
        pid    = request.form.get("product_id")    or None
        msg    = request.form.get("message",       "").strip()
        if not cname or not phone:
            flash("Customer name and phone are required.", "danger")
            return render_template("admin/lead_form.html", products=products, lead=None)
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO leads (customer_name,phone_number,email,product_id,message) VALUES (?,?,?,?,?)",
                (cname, phone, email, pid, msg)
            )
        log_action(g.user["id"], g.user["username"], "LEAD_CREATE", f"New lead: {cname}")
        flash("Lead added.", "success")
        return redirect(url_for("admin_bp.leads"))
    return render_template("admin/lead_form.html", products=products, lead=None)


@admin_bp.route("/leads/<int:lid>", methods=["GET", "POST"])
@login_required
def lead_detail(lid):
    db   = get_db()
    lead = db.execute(
        "SELECT l.*, p.name AS product_name FROM leads l "
        "LEFT JOIN products p ON l.product_id=p.id WHERE l.id=?", (lid,)
    ).fetchone()
    products = db.execute("SELECT id,name FROM products WHERE is_active=1 ORDER BY name").fetchall()
    db.close()
    if not lead:
        abort(404)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update":
            notes  = request.form.get("admin_notes", "")
            status = request.form.get("status", lead["status"])
            with db_conn() as conn:
                conn.execute(
                    "UPDATE leads SET admin_notes=?,status=?,updated_at=datetime('now') WHERE id=?",
                    (notes, status, lid)
                )
            flash("Lead updated.", "success")
        elif action == "convert":
            return redirect(url_for("admin_bp.order_new", lead_id=lid))
        return redirect(url_for("admin_bp.lead_detail", lid=lid))
    return render_template("admin/lead_detail.html", lead=dict(lead), products=products)


# ─────────────────────────────────────────────────────────────────────────────
# ORDERS & INVOICING
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/orders")
@login_required
def orders():
    db     = get_db()
    status = request.args.get("status", "All")
    q      = request.args.get("q", "").strip()
    query  = "SELECT * FROM orders WHERE 1=1"
    params = []
    if status != "All":
        query += " AND status=?"
        params.append(status)
    if q:
        query += " AND (customer_name LIKE ? OR invoice_number LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    query += " ORDER BY created_at DESC"
    all_orders = db.execute(query, params).fetchall()

    # totals per order
    totals = {}
    for o in all_orders:
        row = db.execute(
            "SELECT COALESCE(SUM(total_price),0) AS tot FROM order_items WHERE order_id=?",
            (o["id"],)
        ).fetchone()
        totals[o["id"]] = row["tot"]
    db.close()
    return render_template("admin/orders.html",
        orders=all_orders, totals=totals, active_status=status, q=q)


@admin_bp.route("/orders/new", methods=["GET", "POST"])
@login_required
def order_new():
    import datetime as _dt
    lead_id = request.args.get("lead_id")
    prefill = {}
    if lead_id:
        db   = get_db()
        lead = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        db.close()
        if lead:
            prefill = dict(lead)

    db       = get_db()
    products = db.execute("SELECT id,name FROM products WHERE is_active=1 ORDER BY name").fetchall()
    db.close()

    if request.method == "POST":
        cname       = request.form.get("customer_name",  "").strip()
        cemail      = request.form.get("customer_email", "").strip()
        cphone      = request.form.get("customer_phone", "").strip()
        billing     = request.form.get("billing_address","").strip()
        due         = request.form.get("due_date", str(_dt.date.today()))
        notes       = request.form.get("notes", "")
        lid         = request.form.get("lead_id") or None
        include_tax = 1 if request.form.get("include_tax") else 0

        descs       = request.form.getlist("item_description[]")
        qtys        = request.form.getlist("item_quantity[]")
        units       = request.form.getlist("item_unit[]")
        unit_prices = request.form.getlist("item_unit_price[]")
        pids        = request.form.getlist("item_product_id[]")

        inv_num = next_invoice_number()
        with db_conn() as conn:
            cur = conn.execute(
                "INSERT INTO orders (lead_id,customer_name,customer_email,customer_phone,"
                "billing_address,invoice_number,due_date,include_tax,notes,created_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (lid, cname, cemail, cphone, billing, inv_num, due, include_tax, notes, g.user["id"])
            )
            oid = cur.lastrowid
            for i, desc in enumerate(descs):
                if not desc.strip():
                    continue
                qty   = float(qtys[i])   if i < len(qtys)   else 1
                up    = float(unit_prices[i]) if i < len(unit_prices) else 0
                total = qty * up
                pid   = pids[i] if i < len(pids) and pids[i] else None
                conn.execute(
                    "INSERT INTO order_items (order_id,product_id,description,quantity,unit,unit_price,total_price) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (oid, pid, desc.strip(), qty,
                     units[i] if i < len(units) else "unit", up, total)
                )
                # Decrement stock if this product tracks inventory
                if pid:
                    try:
                        prod = conn.execute("SELECT stock_quantity FROM products WHERE id=?", (pid,)).fetchone()
                        if prod and prod["stock_quantity"] is not None:
                            new_stock = max(0, prod["stock_quantity"] - int(qty))
                            conn.execute("UPDATE products SET stock_quantity=? WHERE id=?", (new_stock, pid))
                    except Exception:
                        pass
            if lid:
                conn.execute("UPDATE leads SET status='converted',updated_at=datetime('now') WHERE id=?", (lid,))

        log_action(g.user["id"], g.user["username"], "ORDER_CREATE", f"Created order {inv_num}")

        # Send order confirmation email to customer if email + SMTP configured
        if cemail:
            try:
                sdb = get_db()
                srow = sdb.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
                sdb.close()
                s = dict(srow) if srow else {}
                if s.get("smtp_user") and s.get("smtp_pass"):
                    total_amt = sum(float(q) * float(p) for q, p in zip(qtys, unit_prices) if q and p)
                    _send_email(
                        cemail,
                        f"Order Confirmation — {inv_num} — Eligald Industrial Chemicals",
                        f"Dear {cname},\n\n"
                        f"Thank you for your order. Here is a summary:\n\n"
                        f"Invoice Number: {inv_num}\n"
                        f"Due Date: {due}\n"
                        f"Estimated Total: KES {total_amt:,.2f}\n\n"
                        f"Our team will be in touch shortly to confirm details and arrange delivery.\n\n"
                        f"Thank you for choosing Eligald Industrial Chemicals Limited.",
                        s
                    )
            except Exception as _e:
                print(f"[ORDER CONFIRM EMAIL] Failed: {_e}")

        flash(f"Order {inv_num} created.", "success")
        return redirect(url_for("admin_bp.order_detail", oid=oid))

    today    = _dt.date.today()
    due_date = (today + _dt.timedelta(days=30)).isoformat()
    return render_template("admin/order_form.html", products=products, prefill=prefill,
                           lead_id=lead_id, today=today.isoformat(), default_due=due_date)


@admin_bp.route("/orders/<int:oid>")
@login_required
def order_detail(oid):
    db    = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not order:
        db.close(); abort(404)
    items = db.execute(
        "SELECT oi.*, p.name AS product_name FROM order_items oi "
        "LEFT JOIN products p ON oi.product_id=p.id WHERE oi.order_id=?", (oid,)
    ).fetchall()
    total = sum(i["total_price"] for i in items)
    db.close()
    return render_template("admin/order_detail.html",
                           order=dict(order), items=items, total=total)


@admin_bp.route("/orders/<int:oid>/status", methods=["POST"])
@login_required
def order_status(oid):
    new_status = request.form.get("status")
    if new_status in ("draft", "sent", "paid", "cancelled"):
        with db_conn() as conn:
            conn.execute(
                "UPDATE orders SET status=?,updated_at=datetime('now') WHERE id=?",
                (new_status, oid)
            )
        if new_status == "paid":
            db = get_db()
            o  = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
            db.close()
            if o and o["created_by"]:
                notify_user(o["created_by"], f"Order {o['invoice_number']} marked as PAID.", f"/admin/orders/{oid}")
        log_action(g.user["id"], g.user["username"], "ORDER_STATUS", f"Order #{oid} → {new_status}")
        flash(f"Order status updated to {new_status}.", "success")
    return redirect(url_for("admin_bp.order_detail", oid=oid))


@admin_bp.route("/orders/<int:oid>/payment", methods=["POST"])
@login_required
def order_payment(oid):
    amount = request.form.get("amount_paid", "0").strip()
    try:
        amount = float(amount) if amount else 0
    except ValueError:
        amount = 0
    method = request.form.get("payment_method", "").strip()
    notes  = request.form.get("payment_notes", "").strip()
    with db_conn() as conn:
        conn.execute(
            "UPDATE orders SET amount_paid=?, payment_method=?, payment_notes=?, updated_at=datetime('now') WHERE id=?",
            (amount, method, notes, oid)
        )
    log_action(g.user["id"], g.user["username"], "ORDER_PAYMENT", f"Order #{oid} payment updated: KES {amount}")
    flash("Payment information updated.", "success")
    return redirect(url_for("admin_bp.order_detail", oid=oid))


@admin_bp.route("/orders/<int:oid>/pdf")
@login_required
def order_pdf(oid):
    db    = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not order:
        db.close(); abort(404)
    items    = db.execute(
        "SELECT * FROM order_items WHERE order_id=?", (oid,)
    ).fetchall()
    settings = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    db.close()

    pdf_bytes = generate_invoice_pdf(dict(order), [dict(i) for i in items], dict(settings))
    with db_conn() as conn:
        conn.execute(
            "UPDATE orders SET status='sent',updated_at=datetime('now') WHERE id=? AND status='draft'",
            (oid,)
        )
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True,
                     download_name=f"{order['invoice_number']}.pdf")


@admin_bp.route("/orders/export-csv")
@login_required
def orders_csv():
    db      = get_db()
    all_orders = db.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    totals  = {}
    for o in all_orders:
        row = db.execute(
            "SELECT COALESCE(SUM(total_price),0) AS tot FROM order_items WHERE order_id=?",
            (o["id"],)
        ).fetchone()
        totals[o["id"]] = row["tot"]
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Invoice #","Customer","Email","Phone","Status","Total","Issued","Due"])
    for o in all_orders:
        writer.writerow([o["invoice_number"], o["customer_name"], o["customer_email"],
                         o["customer_phone"], o["status"], f"{totals[o['id']]:.2f}",
                         o["issued_date"], o["due_date"]])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()),
                     mimetype="text/csv", as_attachment=True,
                     download_name="eligald_orders.csv")


# ─────────────────────────────────────────────────────────────────────────────
# TICKETS
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/tickets")
@login_required
def tickets():
    db     = get_db()
    status = request.args.get("status", "All")
    q      = request.args.get("q", "").strip()
    query  = "SELECT * FROM tickets WHERE 1=1"
    params = []
    if status != "All":
        query += " AND status=?"
        params.append(status)
    if q:
        query += " AND (subject LIKE ? OR name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    query += " ORDER BY created_at DESC"
    all_tickets = db.execute(query, params).fetchall()
    db.close()
    return render_template("admin/tickets.html",
        tickets=all_tickets, active_status=status, q=q)


@admin_bp.route("/tickets/<int:tid>", methods=["GET", "POST"])
@login_required
def ticket_detail(tid):
    db = get_db()
    ticket  = db.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    if not ticket:
        db.close(); abort(404)
    replies = db.execute(
        "SELECT tr.*, u.username FROM ticket_replies tr "
        "LEFT JOIN users u ON tr.user_id=u.id WHERE tr.ticket_id=? ORDER BY tr.created_at",
        (tid,)
    ).fetchall()
    db.close()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "reply":
            msg = request.form.get("message", "").strip()
            if msg:
                with db_conn() as conn:
                    conn.execute(
                        "INSERT INTO ticket_replies (ticket_id,user_id,message) VALUES (?,?,?)",
                        (tid, g.user["id"], msg)
                    )
                    conn.execute(
                        "UPDATE tickets SET status='in_progress',updated_at=datetime('now') WHERE id=? AND status='open'",
                        (tid,)
                    )
                flash("Reply added.", "success")
        elif action == "status":
            new_st = request.form.get("status")
            if new_st in ("open", "in_progress", "closed"):
                with db_conn() as conn:
                    conn.execute(
                        "UPDATE tickets SET status=?,updated_at=datetime('now') WHERE id=?",
                        (new_st, tid)
                    )
                log_action(g.user["id"], g.user["username"], "TICKET_STATUS",
                           f"Ticket #{tid} → {new_st}")
                flash(f"Ticket status changed to {new_st}.", "success")
        return redirect(url_for("admin_bp.ticket_detail", tid=tid))

    return render_template("admin/ticket_detail.html",
                           ticket=dict(ticket), replies=replies)


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/notifications")
@login_required
def notifications():
    db    = get_db()
    notifs = db.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return render_template("admin/notifications.html", notifications=notifs)


@admin_bp.route("/notifications/unread-count")
@login_required
def notif_unread_count():
    db  = get_db()
    cnt = db.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
        (g.user["id"],)
    ).fetchone()[0]
    db.close()
    return jsonify({"count": cnt})


@admin_bp.route("/notifications/preview")
@login_required
def notif_preview():
    db = get_db()
    notifs = db.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify({"notifications": [dict(n) for n in notifs]})


@admin_bp.route("/notifications/<int:nid>/read")
@login_required
def notif_read(nid):
    db   = get_db()
    notif = db.execute("SELECT * FROM notifications WHERE id=? AND user_id=?",
                       (nid, g.user["id"])).fetchone()
    db.close()
    if notif:
        with db_conn() as conn:
            conn.execute("UPDATE notifications SET is_read=1 WHERE id=?", (nid,))
        if notif["link"]:
            return redirect(notif["link"])
    return redirect(url_for("admin_bp.notifications"))


@admin_bp.route("/notifications/mark-all-read", methods=["POST"])
@login_required
def notif_mark_all_read():
    with db_conn() as conn:
        conn.execute(
            "UPDATE notifications SET is_read=1 WHERE user_id=?", (g.user["id"],)
        )
    return redirect(url_for("admin_bp.notifications"))


# ─────────────────────────────────────────────────────────────────────────────
# SITE SETTINGS (super_admin only)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/settings", methods=["GET", "POST"])
@super_admin_required
def settings():
    db  = get_db()
    row = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    db.close()
    if request.method == "POST":
        fields = [
            "company_name", "address", "phone", "whatsapp_number", "email",
            "about_us_text", "mission_text", "vision_text",
            "facebook_url",  "linkedin_url", "twitter_url",
            "hero_tagline",  "hero_subheading",
        ]
        values = {f: request.form.get(f, "").strip() for f in fields}

        # Logo upload
        logo_url = dict(row).get("logo_url", "")
        if "logo_file" in request.files:
            lf = request.files["logo_file"]
            if lf and lf.filename and allowed_file(lf.filename):
                logo_url = save_upload(lf, "logos")
        values["logo_url"] = logo_url

        set_clause = ", ".join(f"{k}=?" for k in values)
        with db_conn() as conn:
            conn.execute(
                f"UPDATE site_settings SET {set_clause} WHERE id=1",
                list(values.values())
            )
        log_action(g.user["id"], g.user["username"], "SETTINGS_UPDATE", "Updated site settings")
        flash("Site settings saved.", "success")
        return redirect(url_for("admin_bp.settings"))

    return render_template("admin/settings.html", s=dict(row) if row else {})


# ─────────────────────────────────────────────────────────────────────────────
# USER MANAGEMENT (super_admin only)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/users")
@super_admin_required
def users():
    db       = get_db()
    all_users = db.execute("SELECT * FROM users ORDER BY created_at").fetchall()
    db.close()
    return render_template("admin/users.html", users=all_users)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@super_admin_required
def user_new():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role     = request.form.get("role", "admin")
        email    = request.form.get("email", "").strip()
        wa_num   = request.form.get("whatsapp_number", "").strip()
        two_fa   = 1 if request.form.get("two_factor_enabled") and wa_num else 0
        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("admin/user_form.html", user=None)
        db = get_db()
        exists = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        db.close()
        if exists:
            flash("Username already taken.", "danger")
            return render_template("admin/user_form.html", user=None)
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO users (username,password_hash,role,email,whatsapp_number,two_factor_enabled,must_change_pw) VALUES (?,?,?,?,?,?,1)",
                (username, generate_password_hash(password), role, email, wa_num, two_fa)
            )
        log_action(g.user["id"], g.user["username"], "USER_CREATE", f"Created user: {username} ({role})")
        flash(f"User '{username}' created.", "success")
        return redirect(url_for("admin_bp.users"))
    return render_template("admin/user_form.html", user=None)


@admin_bp.route("/users/<int:uid>/edit", methods=["GET", "POST"])
@super_admin_required
def user_edit(uid):
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    db.close()
    if not user:
        abort(404)
    if request.method == "POST":
        role     = request.form.get("role", "admin")
        password = request.form.get("password", "").strip()
        email    = request.form.get("email", "").strip()
        wa_num   = request.form.get("whatsapp_number", "").strip()
        two_fa   = 1 if request.form.get("two_factor_enabled") and wa_num else 0
        with db_conn() as conn:
            conn.execute(
                "UPDATE users SET role=?, email=?, whatsapp_number=?, two_factor_enabled=? WHERE id=?",
                (role, email, wa_num, two_fa, uid)
            )
            if password:
                conn.execute(
                    "UPDATE users SET password_hash=?,must_change_pw=0 WHERE id=?",
                    (generate_password_hash(password), uid)
                )
        log_action(g.user["id"], g.user["username"], "USER_EDIT", f"Edited user #{uid}")
        flash("User updated.", "success")
        return redirect(url_for("admin_bp.users"))
    return render_template("admin/user_form.html", user=dict(user))


@admin_bp.route("/users/<int:uid>/delete", methods=["POST"])
@super_admin_required
def user_delete(uid):
    if uid == g.user["id"]:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin_bp.users"))
    db   = get_db()
    user = db.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    db.close()
    if user:
        with db_conn() as conn:
            conn.execute("DELETE FROM users WHERE id=?", (uid,))
        log_action(g.user["id"], g.user["username"], "USER_DELETE", f"Deleted user: {user['username']}")
        flash(f"User '{user['username']}' deleted.", "success")
    return redirect(url_for("admin_bp.users"))


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY LOG (super_admin only)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/activity-log")
@super_admin_required
def activity_log():
    db   = get_db()
    logs = db.execute(
        "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 200"
    ).fetchall()
    db.close()
    return render_template("admin/activity_log.html", logs=logs)


# ─────────────────────────────────────────────────────────────────────────────
# DB BACKUP (super_admin only)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/backup")
@super_admin_required
def backup():
    log_action(g.user["id"], g.user["username"], "DB_BACKUP", "Downloaded database backup")
    return send_file(DB_PATH, as_attachment=True,
                     download_name=f"eligald_backup_{date.today()}.db",
                     mimetype="application/x-sqlite3")

@admin_bp.route("/backups")
@super_admin_required
def backups_list():
    from backup import list_backups, make_backup
    items = list_backups(DB_PATH)
    return render_template("admin/backups.html", backups=items)

@admin_bp.route("/backups/create", methods=["POST"])
@super_admin_required
def backups_create():
    from backup import make_backup
    result = make_backup(DB_PATH)
    if result:
        flash("Backup created successfully.", "success")
    else:
        flash("Backup failed. Check server logs.", "danger")
    return redirect(url_for("admin_bp.backups_list"))

@admin_bp.route("/backups/download/<path:fname>")
@super_admin_required
def backups_download(fname):
    from backup import backup_dir
    safe_name = os.path.basename(fname)
    fpath = os.path.join(backup_dir(DB_PATH), safe_name)
    if not os.path.exists(fpath):
        abort(404)
    return send_file(fpath, as_attachment=True, download_name=safe_name,
                     mimetype="application/x-sqlite3")

# ─────────────────────────────────────────────────────────────────────────────
# NEW ROUTES: Categories, Testimonials, Founders, Customers, Promotions
# ─────────────────────────────────────────────────────────────────────────────

# ─── TESTIMONIALS ─────────────────────────────────────────────────────────────
@admin_bp.route("/testimonials")
@login_required
def testimonials():
    db   = get_db()
    data = db.execute("SELECT * FROM testimonials ORDER BY sort_order, created_at").fetchall()
    db.close()
    return render_template("admin/testimonials.html", testimonials=data)

@admin_bp.route("/testimonials/new", methods=["GET","POST"])
@login_required
def testimonial_new():
    if request.method == "POST":
        cname  = request.form.get("customer_name","").strip()
        company= request.form.get("company","").strip()
        quote  = request.form.get("quote","").strip()
        rating = int(request.form.get("rating", 5))
        sort   = int(request.form.get("sort_order", 0))
        active = 1 if request.form.get("is_active") else 0
        if not cname or not quote:
            flash("Name and quote are required.", "danger")
            return render_template("admin/testimonial_form.html", t=None)
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO testimonials (customer_name,company,quote,rating,sort_order,is_active) VALUES (?,?,?,?,?,?)",
                (cname, company, quote, rating, sort, active)
            )
        flash("Testimonial added.", "success")
        return redirect(url_for("admin_bp.testimonials"))
    return render_template("admin/testimonial_form.html", t=None)

@admin_bp.route("/testimonials/<int:tid>/edit", methods=["GET","POST"])
@login_required
def testimonial_edit(tid):
    db = get_db()
    t  = db.execute("SELECT * FROM testimonials WHERE id=?", (tid,)).fetchone()
    db.close()
    if not t: abort(404)
    if request.method == "POST":
        with db_conn() as conn:
            conn.execute(
                "UPDATE testimonials SET customer_name=?,company=?,quote=?,rating=?,sort_order=?,is_active=? WHERE id=?",
                (request.form.get("customer_name","").strip(),
                 request.form.get("company","").strip(),
                 request.form.get("quote","").strip(),
                 int(request.form.get("rating",5)),
                 int(request.form.get("sort_order",0)),
                 1 if request.form.get("is_active") else 0, tid)
            )
        flash("Testimonial updated.", "success")
        return redirect(url_for("admin_bp.testimonials"))
    return render_template("admin/testimonial_form.html", t=dict(t))

@admin_bp.route("/testimonials/<int:tid>/delete", methods=["POST"])
@login_required
def testimonial_delete(tid):
    with db_conn() as conn:
        conn.execute("DELETE FROM testimonials WHERE id=?", (tid,))
    flash("Testimonial deleted.", "success")
    return redirect(url_for("admin_bp.testimonials"))

# ─── FOUNDERS ─────────────────────────────────────────────────────────────────
@admin_bp.route("/founders")
@super_admin_required
def founders():
    db   = get_db()
    data = db.execute("SELECT * FROM founders ORDER BY sort_order, created_at").fetchall()
    s    = db.execute("SELECT founders_enabled FROM site_settings WHERE id=1").fetchone()
    db.close()
    enabled = s["founders_enabled"] if s else 0
    return render_template("admin/founders.html", founders=data, founders_enabled=enabled)

@admin_bp.route("/founders/toggle", methods=["POST"])
@super_admin_required
def founders_toggle():
    with db_conn() as conn:
        conn.execute("UPDATE site_settings SET founders_enabled=CASE WHEN founders_enabled=1 THEN 0 ELSE 1 END WHERE id=1")
    flash("Founders page visibility updated.", "success")
    return redirect(url_for("admin_bp.founders"))

@admin_bp.route("/founders/new", methods=["GET","POST"])
@super_admin_required
def founder_new():
    if request.method == "POST":
        name      = request.form.get("name","").strip()
        title     = request.form.get("title","").strip()
        bio       = request.form.get("bio","").strip()
        sort      = int(request.form.get("sort_order", 0))
        active    = 1 if request.form.get("is_active") else 0
        photo_url = request.form.get("photo_url","").strip()
        if "photo_file" in request.files:
            f = request.files["photo_file"]
            if f and f.filename and allowed_file(f.filename):
                photo_url = save_upload(f, "products")
        if not name:
            flash("Founder name is required.", "danger")
            return render_template("admin/founder_form.html", founder=None)
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO founders (name,title,bio,photo_url,sort_order,is_active) VALUES (?,?,?,?,?,?)",
                (name, title, bio, photo_url, sort, active)
            )
        log_action(g.user["id"], g.user["username"], "FOUNDER_CREATE", f"Added: {name}")
        flash(f"Founder '{name}' added.", "success")
        return redirect(url_for("admin_bp.founders"))
    return render_template("admin/founder_form.html", founder=None)

@admin_bp.route("/founders/<int:fid>/edit", methods=["GET","POST"])
@super_admin_required
def founder_edit(fid):
    db      = get_db()
    founder = db.execute("SELECT * FROM founders WHERE id=?", (fid,)).fetchone()
    db.close()
    if not founder: abort(404)
    if request.method == "POST":
        photo_url = request.form.get("photo_url", founder["photo_url"])
        if "photo_file" in request.files:
            f = request.files["photo_file"]
            if f and f.filename and allowed_file(f.filename):
                photo_url = save_upload(f, "products")
        with db_conn() as conn:
            conn.execute(
                "UPDATE founders SET name=?,title=?,bio=?,photo_url=?,sort_order=?,is_active=? WHERE id=?",
                (request.form.get("name","").strip(),
                 request.form.get("title","").strip(),
                 request.form.get("bio","").strip(),
                 photo_url,
                 int(request.form.get("sort_order",0)),
                 1 if request.form.get("is_active") else 0, fid)
            )
        flash("Founder updated.", "success")
        return redirect(url_for("admin_bp.founders"))
    return render_template("admin/founder_form.html", founder=dict(founder))

@admin_bp.route("/founders/<int:fid>/delete", methods=["POST"])
@super_admin_required
def founder_delete(fid):
    with db_conn() as conn:
        conn.execute("DELETE FROM founders WHERE id=?", (fid,))
    flash("Founder deleted.", "success")
    return redirect(url_for("admin_bp.founders"))

# ─── CATEGORY MANAGEMENT ──────────────────────────────────────────────────────
@admin_bp.route("/categories")
@super_admin_required
def categories():
    db   = get_db()
    cats = db.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()
    db.close()
    return render_template("admin/categories.html", categories=cats)

@admin_bp.route("/categories/new", methods=["GET","POST"])
@super_admin_required
def category_new():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        desc = request.form.get("description","").strip()
        sort = int(request.form.get("sort_order", 0))
        if not name:
            flash("Category name is required.", "danger")
            return render_template("admin/category_form.html", cat=None)
        try:
            with db_conn() as conn:
                conn.execute("INSERT INTO categories (name,description,sort_order) VALUES (?,?,?)", (name, desc, sort))
            flash(f"Category '{name}' created.", "success")
        except Exception as e:
            flash(f"Error: Category may already exist.", "danger")
        return redirect(url_for("admin_bp.categories"))
    return render_template("admin/category_form.html", cat=None)

@admin_bp.route("/categories/<int:cid>/edit", methods=["GET","POST"])
@super_admin_required
def category_edit(cid):
    db  = get_db()
    cat = db.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()
    db.close()
    if not cat: abort(404)
    if request.method == "POST":
        with db_conn() as conn:
            conn.execute(
                "UPDATE categories SET name=?,description=?,sort_order=?,is_active=? WHERE id=?",
                (request.form.get("name","").strip(),
                 request.form.get("description","").strip(),
                 int(request.form.get("sort_order",0)),
                 1 if request.form.get("is_active") else 0, cid)
            )
        flash("Category updated.", "success")
        return redirect(url_for("admin_bp.categories"))
    return render_template("admin/category_form.html", cat=dict(cat))

@admin_bp.route("/categories/<int:cid>/delete", methods=["POST"])
@super_admin_required
def category_delete(cid):
    with db_conn() as conn:
        conn.execute("DELETE FROM categories WHERE id=?", (cid,))
    flash("Category deleted.", "success")
    return redirect(url_for("admin_bp.categories"))

# ─── CUSTOMERS ────────────────────────────────────────────────────────────────
@admin_bp.route("/customers")
@login_required
def customers():
    db     = get_db()
    q      = request.args.get("q","").strip()
    qry    = "SELECT * FROM customers WHERE 1=1"
    params = []
    if q:
        qry += " AND (name LIKE ? OR email LIKE ? OR phone LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    qry += " ORDER BY created_at DESC"
    all_customers = db.execute(qry, params).fetchall()
    db.close()
    return render_template("admin/customers.html", customers=all_customers, q=q)

@admin_bp.route("/customers/<int:cid>/delete", methods=["POST"])
@login_required
def customer_delete(cid):
    with db_conn() as conn:
        conn.execute("DELETE FROM customers WHERE id=?", (cid,))
    flash("Customer deleted.", "success")
    return redirect(url_for("admin_bp.customers"))

@admin_bp.route("/customers/export-csv")
@login_required
def customers_csv():
    db   = get_db()
    data = db.execute("SELECT * FROM customers ORDER BY created_at DESC").fetchall()
    db.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name","Email","Phone","Source","Marketing Consent","Created"])
    for c in data:
        writer.writerow([c["name"],c["email"],c["phone"],c["source"],
                         "Yes" if c["marketing_consent"] else "No", c["created_at"][:10]])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype="text/csv",
                     as_attachment=True, download_name="eligald_customers.csv")

# ─── PROMOTIONS ───────────────────────────────────────────────────────────────
@admin_bp.route("/promotions")
@login_required
def promotions():
    db   = get_db()
    data = db.execute("SELECT * FROM promotions ORDER BY created_at DESC").fetchall()
    db.close()
    return render_template("admin/promotions.html", promotions=data)

@admin_bp.route("/promotions/new", methods=["GET","POST"])
@login_required
def promotion_new():
    db        = get_db()
    settings  = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    customers = db.execute("SELECT * FROM customers WHERE marketing_consent=1").fetchall()
    db.close()
    if request.method == "POST":
        subject = request.form.get("subject","").strip()
        message = request.form.get("message","").strip()
        channel = request.form.get("channel","email")
        if not message:
            flash("Message is required.", "danger")
            return render_template("admin/promotion_form.html",
                                   settings=dict(settings) if settings else {},
                                   customers=customers)
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO promotions (subject,message,channel,status,created_by) VALUES (?,?,?,'draft',?)",
                (subject, message, channel, g.user["id"])
            )
        flash("Promotion saved as draft.", "success")
        return redirect(url_for("admin_bp.promotions"))
    return render_template("admin/promotion_form.html",
                           settings=dict(settings) if settings else {},
                           customers=customers)

@admin_bp.route("/promotions/<int:pid>/send", methods=["POST"])
@login_required
def promotion_send(pid):
    db        = get_db()
    promo     = db.execute("SELECT * FROM promotions WHERE id=?", (pid,)).fetchone()
    settings  = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    customers = db.execute("SELECT * FROM customers WHERE marketing_consent=1").fetchall()
    db.close()
    if not promo: abort(404)
    s    = dict(settings) if settings else {}
    sent = 0
    for customer in customers:
        if promo["channel"] in ("email","both") and customer["email"]:
            try:
                _send_email(customer["email"],
                    promo["subject"] or "Message from Eligald",
                    promo["message"].replace("{name}", customer["name"]), s)
                sent += 1
            except Exception: pass
        if promo["channel"] in ("whatsapp","both") and customer["phone"]:
            try:
                _send_whatsapp(customer["phone"],
                    promo["message"].replace("{name}", customer["name"]), s)
                sent += 1
            except Exception: pass
    with db_conn() as conn:
        conn.execute("UPDATE promotions SET status='sent',sent_count=?,sent_at=datetime('now') WHERE id=?",
                     (sent, pid))
    flash(f"Promotion sent to {sent} recipients.", "success")
    return redirect(url_for("admin_bp.promotions"))

# ─── Settings test email route ────────────────────────────────────────────────
@admin_bp.route("/settings/test-email", methods=["POST"])
@super_admin_required
def test_email():
    db       = get_db()
    settings = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    db.close()
    s = dict(settings) if settings else {}
    try:
        _send_email(s.get("smtp_user",""),
                    "Eligald Admin — Test Email",
                    "This is a test email. Your Gmail SMTP is configured correctly.",
                    s)
        return jsonify({"success": True, "message": f"Test email sent to {s.get('smtp_user','')}!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

# ─── Email / WhatsApp helpers ─────────────────────────────────────────────────
def _send_email(to_email, subject, body, settings):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    smtp_user = settings.get("smtp_user","")
    smtp_pass = settings.get("smtp_pass","")
    smtp_host = settings.get("smtp_host","smtp.gmail.com")
    smtp_port = int(settings.get("smtp_port", 587) or 587)
    if not smtp_user or not smtp_pass:
        raise ValueError("Gmail SMTP not configured. Go to Admin → Site Settings → Email.")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Eligald Industrial Chemicals <{smtp_user}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo(); server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())

def _send_whatsapp(phone, message, settings):
    import urllib.request
    token    = settings.get("wa_business_token","")
    phone_id = settings.get("wa_phone_id","")
    if not token or not phone_id:
        raise ValueError("WhatsApp Business API not configured.")
    phone = phone.replace("+","").replace(" ","").replace("-","")
    payload = json.dumps({"messaging_product":"whatsapp","to":phone,
                          "type":"text","text":{"body":message}}).encode()
    req = urllib.request.Request(
        f"https://graph.facebook.com/v18.0/{phone_id}/messages",
        data=payload,
        headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"}
    )
    urllib.request.urlopen(req, timeout=10)

# ─── COMPANY STATS MANAGEMENT ─────────────────────────────────────────────────

@admin_bp.route("/stats")
@super_admin_required
def company_stats():
    db   = get_db()
    data = db.execute("SELECT * FROM company_stats ORDER BY sort_order").fetchall()
    db.close()
    return render_template("admin/stats.html", stats=data)

@admin_bp.route("/stats/new", methods=["GET","POST"])
@super_admin_required
def stat_new():
    if request.method == "POST":
        number = request.form.get("number","").strip()
        label  = request.form.get("label","").strip()
        icon   = request.form.get("icon","fa-star").strip()
        sort   = int(request.form.get("sort_order", 0))
        if not number or not label:
            flash("Number and label are required.", "danger")
            return render_template("admin/stat_form.html", stat=None)
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO company_stats (number,label,icon,sort_order) VALUES (?,?,?,?)",
                (number, label, icon, sort)
            )
        flash("Stat added.", "success")
        return redirect(url_for("admin_bp.company_stats"))
    return render_template("admin/stat_form.html", stat=None)

@admin_bp.route("/stats/<int:sid>/edit", methods=["GET","POST"])
@super_admin_required
def stat_edit(sid):
    db = get_db()
    s  = db.execute("SELECT * FROM company_stats WHERE id=?", (sid,)).fetchone()
    db.close()
    if not s: abort(404)
    if request.method == "POST":
        with db_conn() as conn:
            conn.execute(
                "UPDATE company_stats SET number=?,label=?,icon=?,sort_order=?,is_active=? WHERE id=?",
                (request.form.get("number","").strip(),
                 request.form.get("label","").strip(),
                 request.form.get("icon","fa-star").strip(),
                 int(request.form.get("sort_order",0)),
                 1 if request.form.get("is_active") else 0, sid)
            )
        flash("Stat updated.", "success")
        return redirect(url_for("admin_bp.company_stats"))
    return render_template("admin/stat_form.html", stat=dict(s))

@admin_bp.route("/stats/<int:sid>/delete", methods=["POST"])
@super_admin_required
def stat_delete(sid):
    with db_conn() as conn:
        conn.execute("DELETE FROM company_stats WHERE id=?", (sid,))
    flash("Stat deleted.", "success")
    return redirect(url_for("admin_bp.company_stats"))

# ─── WHATSAPP CONTACTS / ENQUIRY EXPORT ───────────────────────────────────────

@admin_bp.route("/whatsapp-contacts")
@login_required
def whatsapp_contacts():
    db   = get_db()
    q    = request.args.get("q","").strip()
    qry  = "SELECT * FROM whatsapp_contacts WHERE 1=1"
    params = []
    if q:
        qry += " AND (name LIKE ? OR phone LIKE ? OR company LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    qry += " ORDER BY created_at DESC"
    contacts = db.execute(qry, params).fetchall()
    db.close()
    return render_template("admin/whatsapp_contacts.html", contacts=contacts, q=q)

@admin_bp.route("/whatsapp-contacts/export-csv")
@login_required
def whatsapp_contacts_csv():
    db   = get_db()
    data = db.execute("SELECT * FROM whatsapp_contacts ORDER BY created_at DESC").fetchall()
    db.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name","Phone","Company","Source","Created"])
    for c in data:
        writer.writerow([c["name"],c["phone"],c["company"],c["source"],c["created_at"][:10]])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype="text/csv",
                     as_attachment=True, download_name="eligald_whatsapp_contacts.csv")

# ─── FEEDBACK MODERATION ───────────────────────────────────────────────────────

@admin_bp.route("/feedback")
@login_required
def feedback():
    db   = get_db()
    filt = request.args.get("status", "all")
    qry  = "SELECT * FROM feedback WHERE 1=1"
    if filt == "pending":
        qry += " AND is_approved=0"
    elif filt == "approved":
        qry += " AND is_approved=1"
    qry += " ORDER BY created_at DESC"
    items = db.execute(qry).fetchall()
    stats = db.execute(
        "SELECT COUNT(*) as cnt, COALESCE(AVG(rating),0) as avg FROM feedback WHERE is_approved=1"
    ).fetchone()
    pending_count = db.execute("SELECT COUNT(*) FROM feedback WHERE is_approved=0").fetchone()[0]
    db.close()
    return render_template("admin/feedback.html", items=items, filt=filt,
                           avg_rating=round(stats["avg"],1) if stats else 0,
                           total_count=stats["cnt"] if stats else 0,
                           pending_count=pending_count)

@admin_bp.route("/feedback/<int:fid>/approve", methods=["POST"])
@login_required
def feedback_approve(fid):
    with db_conn() as conn:
        conn.execute("UPDATE feedback SET is_approved=1 WHERE id=?", (fid,))
    flash("Feedback approved and now visible on site.", "success")
    return redirect(url_for("admin_bp.feedback"))

@admin_bp.route("/feedback/<int:fid>/reject", methods=["POST"])
@login_required
def feedback_reject(fid):
    with db_conn() as conn:
        conn.execute("UPDATE feedback SET is_approved=0 WHERE id=?", (fid,))
    flash("Feedback hidden from site.", "success")
    return redirect(url_for("admin_bp.feedback"))

@admin_bp.route("/feedback/<int:fid>/delete", methods=["POST"])
@login_required
def feedback_delete(fid):
    with db_conn() as conn:
        conn.execute("DELETE FROM feedback WHERE id=?", (fid,))
    flash("Feedback deleted.", "success")
    return redirect(url_for("admin_bp.feedback"))

# ─── ANALYTICS ──────────────────────────────────────────────────────────────

@admin_bp.route("/analytics")
@login_required
def analytics():
    db = get_db()
    top_pages = db.execute(
        "SELECT path, COUNT(*) as views FROM page_views "
        "WHERE created_at >= date('now','-30 days') "
        "GROUP BY path ORDER BY views DESC LIMIT 15"
    ).fetchall()
    top_products = db.execute(
        "SELECT p.name, COUNT(*) as views FROM page_views pv "
        "JOIN products p ON pv.product_id = p.id "
        "WHERE pv.created_at >= date('now','-30 days') "
        "GROUP BY p.id ORDER BY views DESC LIMIT 10"
    ).fetchall()
    total_views = db.execute(
        "SELECT COUNT(*) FROM page_views WHERE created_at >= date('now','-30 days')"
    ).fetchone()[0]
    daily = db.execute(
        "SELECT date(created_at) as d, COUNT(*) as cnt FROM page_views "
        "WHERE created_at >= date('now','-30 days') GROUP BY d ORDER BY d"
    ).fetchall()
    db.close()
    return render_template("admin/analytics.html",
        top_pages=top_pages, top_products=top_products,
        total_views=total_views,
        daily_labels=json.dumps([r["d"] for r in daily]),
        daily_values=json.dumps([r["cnt"] for r in daily]))
