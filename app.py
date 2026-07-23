"""
app.py – Eligald Industrial Chemicals Limited
Production-ready Flask application with full security hardening.
"""

import os, csv, io, json, re
from datetime import datetime, timedelta, date
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, g, flash, jsonify, send_file, abort, Response
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from database   import get_db, init_db, notify_all_admins, log_action, db_conn
from auth       import load_current_user
from csrf       import generate_csrf_token, validate_csrf
from rate_limit import check_rate_limit, rate_limit_response

# ─── App factory ────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key              = os.environ.get("SECRET_KEY", "eligald-change-this-in-production-2025!")
app.permanent_session_lifetime = timedelta(hours=8)

UPLOAD_FOLDER    = os.path.join(app.root_path, "static", "uploads")
ALLOWED_IMG_EXT  = {"png", "jpg", "jpeg", "gif", "webp"}
app.config["UPLOAD_FOLDER"]       = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"]  = 8 * 1024 * 1024   # 8 MB
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = os.environ.get("FLASK_ENV") == "production"

os.makedirs(os.path.join(UPLOAD_FOLDER, "products"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, "logos"),    exist_ok=True)

# ─── CSRF global helper ──────────────────────────────────────────────────────
app.jinja_env.globals["csrf_token"] = generate_csrf_token

# ─── Admin blueprint ─────────────────────────────────────────────────────────
from blueprints.admin import admin_bp
app.register_blueprint(admin_bp, url_prefix="/admin")

# ═══════════════════════════════════════════════════════════════════════════
# SECURITY HEADERS
# ═══════════════════════════════════════════════════════════════════════════
@app.after_request
def set_security_headers(response):
    # Content-Security-Policy
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
        "https://cdnjs.cloudflare.com https://cdn.jsdelivr.net "
        "https://fonts.googleapis.com https://www.google.com "
        "https://maps.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
        "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https: blob:; "
        "connect-src 'self'; "
        "frame-src https://www.openstreetmap.org https://www.google.com; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "upgrade-insecure-requests;"
    )
    response.headers["Content-Security-Policy"]   = csp
    response.headers["X-Content-Type-Options"]    = "nosniff"
    response.headers["X-Frame-Options"]           = "SAMEORIGIN"
    response.headers["X-XSS-Protection"]          = "1; mode=block"
    response.headers["Referrer-Policy"]           = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]        = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Remove server identification
    response.headers.pop("Server", None)
    return response

# ═══════════════════════════════════════════════════════════════════════════
# BEFORE REQUEST
# ═══════════════════════════════════════════════════════════════════════════
@app.before_request
def before_request():
    load_current_user()
    validate_csrf()
    generate_csrf_token()
    db  = get_db()
    row = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    db.close()
    g.settings = dict(row) if row else {}

# ─── Context processor ───────────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    s  = g.get("settings", {})
    wa = s.get("whatsapp_number", "254719655694")
    wa_msg_encoded = (
        "%F0%9F%91%8B%20Hello%20Eligald%20Industrial%20Chemicals%20Limited%2C%0A%0A"
        "I%20would%20like%20to%20enquire%20about%20your%20industrial%20chemicals.%0A%0A"
        "Product%20Name%3A%0A"
        "Quantity%20Required%3A%0A"
        "Application%2FUse%3A%0A"
        "Delivery%20Location%3A%0A"
        "Company%20Name%20(Optional)%3A%0A%0A"
        "Kindly%20share%3A%0A"
        "%E2%9C%85%20Availability%0A"
        "%E2%9C%85%20Price%20quotation%0A"
        "%E2%9C%85%20Delivery%20timeline%0A"
        "%E2%9C%85%20Payment%20options%0A%0A"
        "Thank%20you."
    )
    wa_default = f"https://wa.me/{wa}?text={wa_msg_encoded}"
    return dict(
        company      = s.get("company_name",    "Eligald Industrial Chemicals Limited"),
        email        = s.get("email",           "eligald.chemicals26@gmail.com"),
        phone        = s.get("phone",           "+254 719 655 694"),
        address      = s.get("address",         "123 Chemical Lane, Industrial City, IC 00000"),
        wa_default   = wa_default,
        wa_number    = wa,
        settings     = s,
        current_user = g.get("user"),
        now          = datetime.now(),
        now_date     = date.today().isoformat(),
    )

# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    db       = get_db()
    featured = db.execute("SELECT * FROM products WHERE is_active=1 ORDER BY id LIMIT 6").fetchall()
    testimonials = db.execute(
        "SELECT * FROM testimonials WHERE is_active=1 ORDER BY sort_order LIMIT 6"
    ).fetchall() if _table_exists(db, "testimonials") else []
    db.close()
    return render_template("index.html", featured=featured,
                           services=SERVICES, testimonials=testimonials)


@app.route("/about")
def about():
    return render_template("about.html", team=TEAM, settings=g.settings)


@app.route("/products")
def products():
    db         = get_db()
    category   = request.args.get("category", "All")
    categories = ["All"] + [r[0] for r in db.execute(
        "SELECT DISTINCT category FROM products WHERE is_active=1 ORDER BY category"
    ).fetchall()]
    if category == "All":
        prods = db.execute("SELECT * FROM products WHERE is_active=1 ORDER BY name").fetchall()
    else:
        prods = db.execute(
            "SELECT * FROM products WHERE is_active=1 AND category=? ORDER BY name", (category,)
        ).fetchall()
    db.close()
    return render_template("products.html", products=prods,
                           categories=categories, active_cat=category)


@app.route("/products/<int:product_id>")
def product_detail(product_id):
    db      = get_db()
    product = db.execute("SELECT * FROM products WHERE id=? AND is_active=1", (product_id,)).fetchone()
    if not product:
        db.close(); abort(404)
    p = dict(product)
    # Parse specs text into dict
    specs = {}
    for line in (p.get("specifications") or "").splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            specs[k.strip()] = v.strip()
    p["specs"] = specs
    # Related products
    related = db.execute(
        "SELECT * FROM products WHERE is_active=1 AND category=? AND id!=? ORDER BY RANDOM() LIMIT 3",
        (p["category"], product_id)
    ).fetchall()
    db.close()
    wa  = g.settings.get("whatsapp_number", "254719655694")
    wa_msg = (
        f"👋 Hello Eligald Industrial Chemicals Limited,\n\n"
        f"I would like to enquire about your industrial chemicals.\n\n"
        f"*Product Name:* {p['name']}\n"
        f"*Quantity Required:* \n"
        f"*Application/Use:* \n"
        f"*Delivery Location:* \n"
        f"*Company Name:* \n\n"
        f"Kindly share:\n"
        f"✅ Availability\n"
        f"✅ Price quotation\n"
        f"✅ Delivery timeline\n"
        f"✅ Payment options\n\n"
        f"Thank you."
    )
    return render_template("product_detail.html", product=p,
                           related=related, wa_msg=wa_msg, wa_number=wa)


@app.route("/services")
def services():
    return render_template("services.html", services=SERVICES)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        # Rate limit: 5 contact submissions per 10 minutes per IP
        if not check_rate_limit("contact", limit=5, window=600):
            return rate_limit_response("contact form")
        name    = request.form.get("name",    "").strip()
        email   = request.form.get("email",   "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        # Basic validation
        if not all([name, email, subject, message]):
            return jsonify({"success": False, "error": "All fields are required."}), 400
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({"success": False, "error": "Invalid email address."}), 400
        db  = get_db()
        cur = db.execute(
            "INSERT INTO tickets (name,email,subject,message,status) VALUES (?,?,?,?,'open')",
            (name[:100], email[:200], subject[:200], message[:2000])
        )
        ticket_id = cur.lastrowid
        db.commit(); db.close()
        notify_all_admins(
            f"New support ticket from {name}: '{subject}'",
            link=f"/admin/tickets/{ticket_id}"
        )
        return jsonify({"success": True})
    return render_template("contact.html")


# ═══════════════════════════════════════════════════════════════════════════
# SEO & TECHNICAL ROUTES
# ═══════════════════════════════════════════════════════════════════════════


@app.route("/founders")
def founders():
    db = get_db()
    s  = db.execute("SELECT founders_enabled FROM site_settings WHERE id=1").fetchone()
    if not s or not s["founders_enabled"]:
        abort(404)
    founders = db.execute(
        "SELECT * FROM founders WHERE is_active=1 ORDER BY sort_order"
    ).fetchall()
    db.close()
    return render_template("founders.html", founders=founders)

@app.route("/sitemap.xml")
def sitemap():
    db       = get_db()
    products = db.execute("SELECT id, updated_at FROM products WHERE is_active=1").fetchall()
    db.close()
    base = request.url_root.rstrip("/")
    pages = [
        {"loc": base + "/",          "priority": "1.0",  "changefreq": "weekly"},
        {"loc": base + "/about",     "priority": "0.7",  "changefreq": "monthly"},
        {"loc": base + "/products",  "priority": "0.9",  "changefreq": "weekly"},
        {"loc": base + "/services",  "priority": "0.8",  "changefreq": "monthly"},
        {"loc": base + "/contact",   "priority": "0.6",  "changefreq": "yearly"},
    ]
    for p in products:
        pages.append({
            "loc":        f"{base}/products/{p['id']}",
            "priority":   "0.8",
            "changefreq": "weekly",
            "lastmod":    (p["updated_at"] or "")[:10],
        })
    xml = render_template("sitemap.xml", pages=pages)
    return Response(xml, mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /static/uploads/",
        f"Sitemap: {request.url_root.rstrip('/')}/sitemap.xml",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/.well-known/security.txt")
def security_txt():
    s = g.get("settings", {})
    email = s.get("email", "eligald.chemicals26@gmail.com")
    txt = (
        f"Contact: mailto:{email}\n"
        "Preferred-Languages: en\n"
        "Policy: /privacy\n"
    )
    return Response(txt, mimetype="text/plain")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


# ═══════════════════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400,
        title="Bad Request",
        message=str(e.description) if hasattr(e, 'description') else "Invalid request."), 400

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403,
        title="Forbidden",
        message="You don't have permission to access this page."), 403

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(413)
def too_large(e):
    flash("File too large. Maximum size is 8 MB.", "danger")
    return redirect(request.referrer or url_for("index"))

@app.errorhandler(429)
def too_many_requests(e):
    return render_template("error.html", code=429,
        title="Too Many Requests",
        message="You've made too many requests. Please wait a moment before trying again."), 429

@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500,
        title="Server Error",
        message="Something went wrong on our end. Please try again later."), 500

# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _table_exists(db, table_name):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row is not None

# ═══════════════════════════════════════════════════════════════════════════
# STATIC DATA
# ═══════════════════════════════════════════════════════════════════════════

SERVICES = [
    {
        "id": "custom-blending",
        "title": "Custom Blending",
        "icon": "fa-flask",
        "tagline": "Formulated to your exact specification.",
        "desc": "Our chemists work directly with your R&D and production teams to develop custom blends, dilutions, and proprietary formulations. ISO-certified blending suites with full batch traceability.",
        "bullets": ["ISO 9001-certified blending facility", "Lab-scale to full production runs",
                    "Full CoA and batch traceability", "NDA / trade-secret protected formulations",
                    "Regulatory support (SDS, UN classification)"],
        "wa_msg": "👋 Hello Eligald Industrial Chemicals Limited,\n\nI would like to enquire about your *Custom Blending* service.\n\n*Product/Chemical:* \n*Required Specification:* \n*Volume Required:* \n*Delivery Location:* \n\nKindly share:\n✅ Availability\n✅ Price quotation\n✅ Delivery timeline\n✅ Payment options\n\nThank you.",
    },
    {
        "id": "logistics-supply",
        "title": "Logistics & Supply",
        "icon": "fa-truck",
        "tagline": "Cold-chain, hazmat, and bulk-liquid expertise.",
        "desc": "ADR-certified tankers and a network of approved carriers for regional and international delivery of bulk and packaged hazardous goods. Full hazmat documentation handled.",
        "bullets": ["ADR/IMDG certified hazmat transport", "Temperature-controlled options",
                    "Real-time shipment tracking", "Import/export documentation support",
                    "Scheduled replenishment contracts"],
        "wa_msg": "👋 Hello Eligald Industrial Chemicals Limited,\n\nI would like to enquire about your *Logistics & Supply* service.\n\n*Chemical/Product:* \n*Volume/Weight:* \n*Pickup Location:* \n*Delivery Location:* \n\nKindly share:\n✅ Availability\n✅ Price quotation\n✅ Delivery timeline\n✅ Payment options\n\nThank you.",
    },
    {
        "id": "technical-consultation",
        "title": "Technical Consultation",
        "icon": "fa-microscope",
        "tagline": "Expert guidance from application to compliance.",
        "desc": "Registered chemists and process engineers provide on-site and remote support across chemical selection, process optimisation, waste neutralisation, and regulatory compliance.",
        "bullets": ["Registered chemists and process engineers", "On-site or remote consultation",
                    "REACH, EPA, GHS compliance audits", "Process optimisation studies",
                    "Staff safety and handling training"],
        "wa_msg": "👋 Hello Eligald Industrial Chemicals Limited,\n\nI would like to enquire about your *Technical Consultation* service.\n\n*Industry/Sector:* \n*Challenge/Requirement:* \n*Location:* \n\nKindly share:\n✅ Availability\n✅ Price quotation\n✅ Delivery timeline\n✅ Payment options\n\nThank you.",
    },
]

TEAM = [
    {"name": "Dr. Eleanor Marsh",  "role": "Chief Executive Officer",      "avatar": "https://randomuser.me/api/portraits/women/44.jpg", "bio": "25 years in industrial chemical distribution across three continents."},
    {"name": "James Okafor",       "role": "Head of Operations",           "avatar": "https://randomuser.me/api/portraits/men/32.jpg",   "bio": "Logistics and supply-chain specialist with ADR fleet management expertise."},
    {"name": "Dr. Sofia Reyes",    "role": "Technical Director",           "avatar": "https://randomuser.me/api/portraits/women/68.jpg", "bio": "PhD Chemistry – process optimisation and hazardous-material compliance."},
    {"name": "Michael Tan",        "role": "Sales & Business Development", "avatar": "https://randomuser.me/api/portraits/men/75.jpg",   "bio": "B2B industrial sales leader with a 200-client portfolio."},
]

# ─── Startup: always init DB (works for gunicorn + local) ───────────────────
with app.app_context():
    try:
        init_db()
        # Safe migrations — add columns if they don't exist yet
        import sqlite3 as _sqlite3
        from database import DB_PATH as _DB_PATH
        _conn = _sqlite3.connect(_DB_PATH)
        for _sql in [
            "ALTER TABLE orders ADD COLUMN include_tax INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE site_settings ADD COLUMN founders_enabled INTEGER NOT NULL DEFAULT 0",
            """CREATE TABLE IF NOT EXISTS founders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, title TEXT DEFAULT '',
                bio TEXT DEFAULT '', photo_url TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')))""",
        ]:
            try:
                _conn.execute(_sql)
                _conn.commit()
            except Exception:
                pass   # Column/table already exists
        _conn.close()
    except Exception as _e:
        print(f"[STARTUP] DB init warning: {_e}")

# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=8080)
