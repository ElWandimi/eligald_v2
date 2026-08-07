"""
app.py – Eligald Industrial Chemicals Limited
Production-ready Flask application with full security hardening.
"""
import os, csv, io, json, re
from urllib.parse import quote
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

# ─── App ─────────────────────────────────────────────────────────────────────
app = Flask(__name__)
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get("RAILWAY_ENVIRONMENT"):
        print("[SECURITY WARNING] SECRET_KEY env var not set in production! Set it in Railway → Variables.")
    _secret = "eligald-dev-only-CHANGE-ME-" + os.urandom(8).hex()
app.secret_key = _secret
app.permanent_session_lifetime = timedelta(hours=8)

UPLOAD_FOLDER    = os.path.join(app.root_path, "static", "uploads")
ALLOWED_IMG_EXT  = {"png", "jpg", "jpeg", "gif", "webp"}
app.config["UPLOAD_FOLDER"]       = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"]  = 8 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = os.environ.get("FLASK_ENV") == "production"

os.makedirs(os.path.join(UPLOAD_FOLDER, "products"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, "logos"),    exist_ok=True)

app.jinja_env.globals["csrf_token"] = generate_csrf_token

from blueprints.admin import admin_bp
app.register_blueprint(admin_bp, url_prefix="/admin")

# ─── Security Headers ─────────────────────────────────────────────────────────
@app.after_request
def set_security_headers(response):
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https: blob:; "
        "connect-src 'self'; "
        "frame-src https://www.openstreetmap.org https://www.google.com; "
        "object-src 'none'; base-uri 'self'; form-action 'self';"
    )
    response.headers["Content-Security-Policy"]   = csp
    response.headers["X-Content-Type-Options"]    = "nosniff"
    response.headers["X-Frame-Options"]           = "SAMEORIGIN"
    response.headers["X-XSS-Protection"]          = "1; mode=block"
    response.headers["Referrer-Policy"]           = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]        = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers.pop("Server", None)
    return response

# ─── Before Request ──────────────────────────────────────────────────────────
@app.before_request
def before_request():
    load_current_user()
    validate_csrf()
    generate_csrf_token()
    db  = get_db()
    row = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    g.settings = dict(row) if row else {}
    # Lightweight page-view tracking for public GET pages (skip admin/static/api)
    try:
        if (request.method == "GET" and not request.path.startswith("/admin")
                and not request.path.startswith("/static")
                and not request.path.endswith((".xml", ".txt", ".pdf"))):
            pid = None
            if request.path.startswith("/products/"):
                try: pid = int(request.path.rsplit("/", 1)[-1])
                except (ValueError, IndexError): pass
            db.execute("INSERT INTO page_views (path, product_id) VALUES (?,?)",
                      (request.path[:200], pid))
            db.commit()
    except Exception:
        pass
    db.close()

@app.context_processor
def inject_globals():
    s  = g.get("settings", {})
    wa = s.get("whatsapp_number", "254719655694")
    try:
        _db = get_db()
        nav_categories = _db.execute(
            "SELECT name FROM categories WHERE is_active=1 ORDER BY sort_order,name"
        ).fetchall()
        _db.close()
    except Exception:
        nav_categories = []
    _default_wa_text = (
        "Hi Eligald team,\n\n"
        "I'd like to enquire about a chemical order. Could you help with the following?\n\n"
        "• Product:\n"
        "• Quantity needed:\n"
        "• Application/use:\n"
        "• Delivery location:\n"
        "• Company (if applicable):\n\n"
        "Please send me pricing, availability, and delivery timeline when you get a chance. Thanks!"
    )
    wa_default = f"https://wa.me/{wa}?text={quote(_default_wa_text)}"
    try:
        _db2 = get_db()
        _fb = _db2.execute(
            "SELECT COUNT(*) as cnt, COALESCE(AVG(rating),0) as avg FROM feedback WHERE is_approved=1"
        ).fetchone()
        _db2.close()
        feedback_count = _fb["cnt"] if _fb else 0
        feedback_avg   = round(_fb["avg"], 1) if _fb and _fb["cnt"] > 0 else 0
    except Exception:
        feedback_count = 0
        feedback_avg   = 0
    return dict(
        company      = s.get("company_name", "Eligald Industrial Chemicals Limited"),
        email        = s.get("email",        "eligald.chemicals26@gmail.com"),
        phone        = s.get("phone",        "+254 719 655 694"),
        address      = s.get("address",      "Imara Daima, Along Enterprise Road, Opp SMK Business Centre, Nairobi, Kenya"),
        wa_default   = wa_default,
        wa_number    = wa,
        settings     = s,
        current_user = g.get("user"),
        nav_categories = nav_categories,
        feedback_count = feedback_count,
        feedback_avg   = feedback_avg,
        now          = datetime.now(),
        now_date     = date.today().isoformat(),
    )

# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    db           = get_db()
    featured     = []
    suggested    = []
    testimonials = []
    categories   = []
    stats        = []
    team         = []
    team_visible = 0
    try:
        # Diverse featured products — one random product per category, spread across
        # up to 8 categories, re-shuffled (both which products AND their order) on every load.
        featured_rows = db.execute("""
            SELECT p.* FROM products p
            INNER JOIN (
                SELECT category, id as pick_id FROM (
                    SELECT category, id,
                           ROW_NUMBER() OVER (PARTITION BY category ORDER BY RANDOM()) as rn
                    FROM products WHERE is_active=1
                ) WHERE rn = 1
            ) picks ON p.id = picks.pick_id
            ORDER BY RANDOM() LIMIT 8
        """).fetchall()
        featured = featured_rows

        # A second diverse set for "You Might Also Like" — different products, still spread
        # across categories, excluding anything already shown in Featured above.
        featured_ids = [str(p["id"]) for p in featured_rows]
        id_list = ','.join(featured_ids) if featured_ids else '0'
        suggested = db.execute(f"""
            SELECT p.* FROM products p
            INNER JOIN (
                SELECT category, id as pick_id FROM (
                    SELECT category, id,
                           ROW_NUMBER() OVER (PARTITION BY category ORDER BY RANDOM()) as rn
                    FROM products
                    WHERE is_active=1 AND id NOT IN ({id_list})
                ) WHERE rn = 1
            ) picks ON p.id = picks.pick_id
            ORDER BY RANDOM() LIMIT 8
        """).fetchall()

        testimonials = db.execute(
            "SELECT * FROM testimonials WHERE is_active=1 ORDER BY sort_order LIMIT 6"
        ).fetchall()
        categories = db.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category=c.name AND p.is_active=1) as product_count "
            "FROM categories c WHERE is_active=1 ORDER BY sort_order LIMIT 16"
        ).fetchall()
        stats = db.execute(
            "SELECT * FROM company_stats WHERE is_active=1 ORDER BY sort_order"
        ).fetchall()
        s = db.execute("SELECT team_visible FROM site_settings WHERE id=1").fetchone()
        team_visible = s["team_visible"] if s else 0
        if team_visible:
            team = db.execute(
                "SELECT * FROM founders WHERE is_active=1 ORDER BY sort_order"
            ).fetchall()
    except Exception: pass
    db.close()
    return render_template("index.html", featured=featured, suggested=suggested,
                           services=SERVICES, testimonials=testimonials,
                           categories=categories, stats=stats,
                           team=team, team_visible=team_visible,
                           CATEGORY_IMAGES=CATEGORY_IMAGES)

@app.route("/about")
def about():
    return render_template("about.html", team=TEAM, settings=g.settings)

@app.route("/products")
def products():
    db       = get_db()
    category = request.args.get("category", "All")
    # Load categories from DB
    try:
        db_cats = [r[0] for r in db.execute(
            "SELECT name FROM categories WHERE is_active=1 ORDER BY sort_order,name"
        ).fetchall()]
    except Exception:
        db_cats = []
    categories = ["All"] + (db_cats or [r[0] for r in db.execute(
        "SELECT DISTINCT category FROM products WHERE is_active=1 ORDER BY category"
    ).fetchall()])
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
    specs = {}
    for line in (p.get("specifications") or "").splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            specs[k.strip()] = v.strip()
    p["specs"] = specs
    related = db.execute(
        "SELECT * FROM products WHERE is_active=1 AND category=? AND id!=? ORDER BY RANDOM() LIMIT 3",
        (p["category"], product_id)
    ).fetchall()
    if len(related) < 3:
        related_ids = [r["id"] for r in related] + [product_id]
        id_list = ','.join(str(i) for i in related_ids)
        extra = db.execute(
            f"SELECT * FROM products WHERE is_active=1 AND id NOT IN ({id_list}) "
            f"ORDER BY RANDOM() LIMIT {3 - len(related)}"
        ).fetchall()
        related = list(related) + list(extra)
    db.close()
    wa  = g.settings.get("whatsapp_number", "254719655694")
    wa_msg = (
        f"Hi Eligald team,\n\n"
        f"I'm interested in ordering *{p['name']}*. Could you send me a quote?\n\n"
        f"• Quantity needed:\n"
        f"• Application/use:\n"
        f"• Delivery location:\n"
        f"• Company (if applicable):\n\n"
        f"Please include pricing, availability, and estimated delivery time. Thanks!"
    )
    return render_template("product_detail.html", product=p,
                           related=related, wa_msg=wa_msg, wa_number=wa)

@app.route("/services")
def services():
    return render_template("services.html", services=SERVICES)

@app.route("/contact", methods=["GET","POST"])
def contact():
    if request.method == "POST":
        if not check_rate_limit("contact", limit=5, window=600):
            return rate_limit_response("contact form")
        name    = request.form.get("name",    "").strip()
        email   = request.form.get("email",   "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        marketing_consent = 1 if request.form.get("marketing_consent") else 0
        if not all([name, email, subject, message]):
            return jsonify({"success": False, "error": "All fields are required."}), 400
        if not request.form.get("tos_accept"):
            return jsonify({"success": False, "error": "Please accept the Terms of Service to continue."}), 400
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({"success": False, "error": "Invalid email address."}), 400
        db  = get_db()
        cur = db.execute(
            "INSERT INTO tickets (name,email,subject,message,status) VALUES (?,?,?,?,'open')",
            (name[:100], email[:200], subject[:200], message[:2000])
        )
        ticket_id = cur.lastrowid
        # Save to customers
        try:
            existing = db.execute("SELECT id FROM customers WHERE email=?", (email[:200],)).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO customers (name,email,source,marketing_consent) VALUES (?,?,?,?)",
                    (name[:100], email[:200], "contact_form", marketing_consent)
                )
            elif marketing_consent:
                db.execute("UPDATE customers SET marketing_consent=1 WHERE email=?", (email[:200],))
        except Exception: pass
        db.commit()
        s = g.get("settings", {})
        # Route to correct business email
        sales_kw = ["sales","order","purchase","quote","price","bulk"]
        notify_email = s.get("email_sales","") if any(kw in subject.lower() for kw in sales_kw) else s.get("email_general","")
        if not notify_email:
            notify_email = s.get("email","")
        if notify_email and s.get("smtp_user") and s.get("smtp_pass"):
            try:
                from blueprints.admin import _send_email
                _send_email(notify_email,
                    f"New Enquiry: {subject} — from {name}",
                    f"Name: {name}\nEmail: {email}\nSubject: {subject}\n\n{message}", s)
            except Exception: pass
        db.close()
        notify_all_admins(f"New support ticket from {name}: '{subject}'",
                          link=f"/admin/tickets/{ticket_id}")
        return jsonify({"success": True})
    return render_template("contact.html")


@app.route("/feedback", methods=["POST"])
def submit_feedback():
    if not check_rate_limit("feedback", limit=5, window=600):
        return rate_limit_response("feedback")
    name    = request.form.get("name", "").strip() or "Anonymous"
    rating  = request.form.get("rating", "").strip()
    comment = request.form.get("comment", "").strip()
    try:
        rating = int(rating)
        assert 1 <= rating <= 5
    except Exception:
        return jsonify({"success": False, "error": "Please select a rating."}), 400
    db = get_db()
    db.execute(
        "INSERT INTO feedback (name, rating, comment) VALUES (?,?,?)",
        (name[:100], rating, comment[:500])
    )
    db.commit()
    db.close()
    notify_all_admins(f"New {rating}-star feedback from {name}", link="/admin/feedback")
    return jsonify({"success": True, "message": "Thank you for your feedback!"})


@app.route("/product-enquiry", methods=["POST"])
def product_enquiry():
    """Lightweight logging for the Quick Enquiry (WhatsApp) modal on product cards."""
    if not check_rate_limit("product_enquiry", limit=10, window=600):
        return rate_limit_response("enquiry")
    name    = request.form.get("name", "").strip()
    product = request.form.get("product", "").strip()
    qty     = request.form.get("quantity", "").strip()
    unit    = request.form.get("unit", "").strip()
    note    = request.form.get("note", "").strip()
    email   = request.form.get("email", "").strip()
    if not name:
        return jsonify({"success": False, "error": "Name is required."}), 400
    if not request.form.get("tos_accept"):
        return jsonify({"success": False, "error": "Please accept the Terms of Service to continue."}), 400
    marketing_consent = 1 if email else 0
    db = get_db()
    if email:
        existing = db.execute("SELECT id FROM customers WHERE email=?", (email,)).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO customers (name,email,phone,source,marketing_consent,notes) VALUES (?,?,?,?,?,?)",
                (name[:100], email[:200], "", "product_enquiry", marketing_consent,
                 f"Enquired about: {product}")
            )
        elif marketing_consent:
            db.execute("UPDATE customers SET marketing_consent=1 WHERE email=?", (email,))
    db.commit()
    db.close()
    notify_all_admins(f"Quick enquiry from {name} — {product}", link="/admin/customers")
    return jsonify({"success": True})


@app.route("/enquiry", methods=["POST"])
def homepage_enquiry():
    if not check_rate_limit("enquiry", limit=5, window=600):
        return rate_limit_response("enquiry form")
    name         = request.form.get("name", "").strip()
    company      = request.form.get("company", "").strip()
    phone_country = request.form.get("phone_country", "+254").strip()
    phone_raw    = request.form.get("phone", "").strip()
    phone        = f"{phone_country} {phone_raw}".strip() if phone_raw else ""
    email        = request.form.get("email", "").strip()
    county       = request.form.get("county", "").strip()
    if not name or not phone_raw:
        return jsonify({"success": False, "error": "Name and WhatsApp number are required."}), 400
    if not request.form.get("tos_accept"):
        return jsonify({"success": False, "error": "Please accept the Terms of Service to continue."}), 400
    marketing_email_consent = 1 if email else 0
    _notes = f"County: {county}" if county else ""
    db = get_db()
    # Save to customers
    existing = db.execute("SELECT id FROM customers WHERE phone=?", (phone,)).fetchone()
    if not existing:
        db.execute(
            "INSERT INTO customers (name,email,phone,company,source,marketing_consent,notes) VALUES (?,?,?,?,?,?,?)",
            (name[:100], email[:200], phone[:30], company[:100], "homepage_enquiry", marketing_email_consent, _notes)
        )
    # Save to whatsapp_contacts
    wa_existing = db.execute("SELECT id FROM whatsapp_contacts WHERE phone=?", (phone,)).fetchone()
    if not wa_existing:
        db.execute(
            "INSERT INTO whatsapp_contacts (name,phone,company,source) VALUES (?,?,?,?)",
            (name[:100], phone[:30], company[:100], "homepage_enquiry")
        )
    db.commit()
    db.close()
    notify_all_admins(f"New homepage enquiry from {name} ({company})", link="/admin/customers")
    return jsonify({"success": True, "message": "Thank you! Our team will contact you shortly on WhatsApp."})

@app.route("/catalogue.pdf")
def catalogue_pdf():
    from pdf_generator import generate_catalogue_pdf
    db = get_db()
    prods = db.execute(
        "SELECT * FROM products WHERE is_active=1 ORDER BY category, name"
    ).fetchall()
    cats = db.execute(
        "SELECT name FROM categories WHERE is_active=1 ORDER BY sort_order,name"
    ).fetchall()
    db.close()
    s = g.get("settings", {})
    pdf_bytes = generate_catalogue_pdf(
        [dict(p) for p in prods], s, categories=[c["name"] for c in cats]
    )
    return Response(pdf_bytes, mimetype="application/pdf", headers={
        "Content-Disposition": "attachment; filename=Eligald_Product_Catalogue.pdf"
    })


@app.route("/founders")
def founders():
    db = get_db()
    s  = db.execute("SELECT founders_enabled FROM site_settings WHERE id=1").fetchone()
    if not s or not s["founders_enabled"]:
        db.close(); abort(404)
    data = db.execute("SELECT * FROM founders WHERE is_active=1 ORDER BY sort_order").fetchall()
    db.close()
    return render_template("founders.html", founders=data)

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/sitemap.xml")
def sitemap():
    db       = get_db()
    prods    = db.execute("SELECT id, updated_at FROM products WHERE is_active=1").fetchall()
    db.close()
    base = request.url_root.rstrip("/")
    pages = [
        {"loc": base+"/",         "priority":"1.0","changefreq":"weekly"},
        {"loc": base+"/about",    "priority":"0.7","changefreq":"monthly"},
        {"loc": base+"/products", "priority":"0.9","changefreq":"weekly"},
        {"loc": base+"/services", "priority":"0.8","changefreq":"monthly"},
        {"loc": base+"/contact",  "priority":"0.6","changefreq":"yearly"},
    ]
    for p in prods:
        pages.append({"loc":f"{base}/products/{p['id']}","priority":"0.8",
                      "changefreq":"weekly","lastmod":(p["updated_at"] or "")[:10]})
    return Response(render_template("sitemap.xml", pages=pages), mimetype="application/xml")

@app.route("/robots.txt")
def robots():
    lines = ["User-agent: *","Allow: /","Disallow: /admin/",
             "Disallow: /static/uploads/",
             f"Sitemap: {request.url_root.rstrip('/')}/sitemap.xml"]
    return Response("\n".join(lines), mimetype="text/plain")

@app.route("/.well-known/security.txt")
def security_txt():
    s     = g.get("settings", {})
    email = s.get("email", "eligald.chemicals26@gmail.com")
    return Response(f"Contact: mailto:{email}\nPreferred-Languages: en\nPolicy: /privacy\n",
                    mimetype="text/plain")

# ─── Error handlers ──────────────────────────────────────────────────────────
@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, title="Bad Request",
        message=str(e.description) if hasattr(e,"description") else "Invalid request."), 400

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, title="Forbidden",
        message="You don't have permission to access this page."), 403

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(429)
def too_many(e):
    return render_template("error.html", code=429, title="Too Many Requests",
        message="Too many requests. Please wait a moment and try again."), 429

@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500, title="Server Error",
        message="Something went wrong on our end. Please try again later."), 500

# ─── Static data ─────────────────────────────────────────────────────────────
CATEGORY_IMAGES = {
    "Agrochemicals": "https://images.unsplash.com/photo-1625246333195-78d9c38ad449?w=600&q=70",
    "Animal Feeds and Veterinary Additives": "https://images.unsplash.com/photo-1516467508483-a7212febe31a?w=600&q=70",
    "Basic Chemicals": "https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?w=600&q=70",
    "Construction Chemicals": "https://images.unsplash.com/photo-1541888946425-d81bb19240f5?w=600&q=70",
    "Dyes and Colours": "https://images.unsplash.com/photo-1615529162924-f8605388461d?w=600&q=70",
    "Food and Beverage Processing Chemicals": "https://images.unsplash.com/photo-1606787366850-de6330128bfc?w=600&q=70",
    "Industrial Acids and Bases": "https://images.unsplash.com/photo-1603126857599-f6e157fa2fe6?w=600&q=70",
    "Industrial Solvents": "https://images.unsplash.com/photo-1614308457932-e21d78ffee94?w=600&q=70",
    "Laboratory and Specialty Reagents": "https://images.unsplash.com/photo-1587854692152-cbe660dbde88?w=600&q=70",
    "Paints, Ink and Coatings": "https://images.unsplash.com/photo-1562259949-e8e7689d7828?w=600&q=70",
    "Personal Care and Cosmetics Ingredients": "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=600&q=70",
    "Petroleum Chemicals": "https://images.unsplash.com/photo-1518709268805-4e9042af2176?w=600&q=70",
    "Plastics and Packaging Raw Materials": "https://images.unsplash.com/photo-1605600659873-d808a13e4d2a?w=600&q=70",
    "Soap and Detergents": "https://images.unsplash.com/photo-1585421514284-efb74320f6a9?w=600&q=70",
    "Textile, Rubber and Leather Processing": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600&q=70",
    "Water Treatments": "https://images.unsplash.com/photo-1548839140-29a749e1cf4d?w=600&q=70",
}

# Multiple distinct photos per category so products within the same category
# never share an identical image. Each product gets one deterministically,
# based on its name, so the assignment is stable across restarts.
CATEGORY_IMAGE_POOL = {
    "Agrochemicals": [
        "https://images.unsplash.com/photo-1625246333195-78d9c38ad449?w=600&q=70",
        "https://images.unsplash.com/photo-1500651230702-0e2d8a49d4ad?w=600&q=70",
        "https://images.unsplash.com/photo-1592982537447-7440770cbfc9?w=600&q=70",
        "https://images.unsplash.com/photo-1523348837708-15d4a09cfac2?w=600&q=70",
        "https://images.unsplash.com/photo-1592982537447-6be5f337535d?w=600&q=70",
        "https://images.unsplash.com/photo-1625246333195-b933f0d5f60c?w=600&q=70",
    ],
    "Animal Feeds and Veterinary Additives": [
        "https://images.unsplash.com/photo-1516467508483-a7212febe31a?w=600&q=70",
        "https://images.unsplash.com/photo-1500595046743-cd271d694d30?w=600&q=70",
        "https://images.unsplash.com/photo-1470093851219-69951fcbb533?w=600&q=70",
        "https://images.unsplash.com/photo-1516467508483-a7212febe31a?w=600&q=70&sat=-30",
    ],
    "Basic Chemicals": [
        "https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?w=600&q=70",
        "https://images.unsplash.com/photo-1603126857599-f6e157fa2fe6?w=600&q=70",
        "https://images.unsplash.com/photo-1587854692152-cbe660dbde88?w=600&q=70",
        "https://images.unsplash.com/photo-1614308457932-e21d78ffee94?w=600&q=70",
        "https://images.unsplash.com/photo-1628863353691-0071c8c1874c?w=600&q=70",
        "https://images.unsplash.com/photo-1616499370260-485b3e5ed3bf?w=600&q=70",
    ],
    "Construction Chemicals": [
        "https://images.unsplash.com/photo-1541888946425-d81bb19240f5?w=600&q=70",
        "https://images.unsplash.com/photo-1541976590-713941681591?w=600&q=70",
        "https://images.unsplash.com/photo-1503387837-b154d5074bd2?w=600&q=70",
    ],
    "Dyes and Colours": [
        "https://images.unsplash.com/photo-1615529162924-f8605388461d?w=600&q=70",
        "https://images.unsplash.com/photo-1541675154750-0444c7d51e8e?w=600&q=70",
        "https://images.unsplash.com/photo-1541675154750-0444c7d51e8e?w=600&q=70&sat=40",
    ],
    "Food and Beverage Processing Chemicals": [
        "https://images.unsplash.com/photo-1606787366850-de6330128bfc?w=600&q=70",
        "https://images.unsplash.com/photo-1490818387583-1baba5e638af?w=600&q=70",
        "https://images.unsplash.com/photo-1550989460-0adf9ea622e2?w=600&q=70",
        "https://images.unsplash.com/photo-1606787366850-de6330128bfc?w=600&q=70&sat=-20",
        "https://images.unsplash.com/photo-1587049352846-4a222e784d38?w=600&q=70",
    ],
    "Industrial Acids and Bases": [
        "https://images.unsplash.com/photo-1603126857599-f6e157fa2fe6?w=600&q=70",
        "https://images.unsplash.com/photo-1628863353691-0071c8c1874c?w=600&q=70",
        "https://images.unsplash.com/photo-1616499370260-485b3e5ed3bf?w=600&q=70",
    ],
    "Industrial Solvents": [
        "https://images.unsplash.com/photo-1614308457932-e21d78ffee94?w=600&q=70",
        "https://images.unsplash.com/photo-1576086213369-97a306d36557?w=600&q=70",
        "https://images.unsplash.com/photo-1612817288484-6f916006741a?w=600&q=70",
        "https://images.unsplash.com/photo-1582719471137-c3967ffb1c42?w=600&q=70",
    ],
    "Laboratory and Specialty Reagents": [
        "https://images.unsplash.com/photo-1587854692152-cbe660dbde88?w=600&q=70",
        "https://images.unsplash.com/photo-1605101100278-5d1deb2b6498?w=600&q=70",
        "https://images.unsplash.com/photo-1554475900-0a0350e3fc7b?w=600&q=70",
    ],
    "Paints, Ink and Coatings": [
        "https://images.unsplash.com/photo-1562259949-e8e7689d7828?w=600&q=70",
        "https://images.unsplash.com/photo-1541675154750-0444c7d51e8e?w=600&q=70",
        "https://images.unsplash.com/photo-1579762593175-20226054cad0?w=600&q=70",
        "https://images.unsplash.com/photo-1487958449943-2429e8be8625?w=600&q=70",
    ],
    "Personal Care and Cosmetics Ingredients": [
        "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=600&q=70",
        "https://images.unsplash.com/photo-1571781926291-c477ebfd024b?w=600&q=70",
        "https://images.unsplash.com/photo-1512496015851-a90fb38ba796?w=600&q=70",
        "https://images.unsplash.com/photo-1596462502278-27bfdc403348?w=600&q=70",
    ],
    "Petroleum Chemicals": [
        "https://images.unsplash.com/photo-1518709268805-4e9042af2176?w=600&q=70",
        "https://images.unsplash.com/photo-1615877330125-31d31c1e2a29?w=600&q=70",
    ],
    "Plastics and Packaging Raw Materials": [
        "https://images.unsplash.com/photo-1605600659873-d808a13e4d2a?w=600&q=70",
        "https://images.unsplash.com/photo-1591196616741-8d15c9c04a11?w=600&q=70",
        "https://images.unsplash.com/photo-1610470752942-4300639b2148?w=600&q=70",
    ],
    "Soap and Detergents": [
        "https://images.unsplash.com/photo-1585421514284-efb74320f6a9?w=600&q=70",
        "https://images.unsplash.com/photo-1585421514738-01798e348b17?w=600&q=70",
        "https://images.unsplash.com/photo-1600857062241-98e5dba7f214?w=600&q=70",
    ],
    "Textile, Rubber and Leather Processing": [
        "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600&q=70",
        "https://images.unsplash.com/photo-1528459801416-a9e53bbf4e17?w=600&q=70",
        "https://images.unsplash.com/photo-1509909756405-be0199881695?w=600&q=70",
    ],
    "Water Treatments": [
        "https://images.unsplash.com/photo-1548839140-29a749e1cf4d?w=600&q=70",
        "https://images.unsplash.com/photo-1548839140-29a749e1cf4d?w=600&q=70&sat=30",
        "https://images.unsplash.com/photo-1544966503-7cc531b16688?w=600&q=70",
        "https://images.unsplash.com/photo-1519046904884-53103b34b206?w=600&q=70",
        "https://images.unsplash.com/photo-1548839140-29a749e1cf4d?w=600&q=70&sat=-30",
    ],
}

def _product_image_for(name, category):
    """Deterministically assign a distinct image to a product within its category pool."""
    pool = CATEGORY_IMAGE_POOL.get(category) or [CATEGORY_IMAGES.get(
        category, "https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?w=600&q=70")]
    idx = sum(ord(c) for c in name) % len(pool)
    return pool[idx]

SERVICES = [
    {"id":"custom-blending","title":"Custom Blending","icon":"fa-flask","tagline":"Formulated to your exact specification.",
     "desc":"Our chemists develop custom blends, dilutions, and proprietary formulations with full batch traceability.",
     "bullets":["ISO 9001-certified blending facility","Lab-scale to full production runs","Full CoA and batch traceability","NDA protected formulations","Regulatory support (SDS, UN classification)"],
     "wa_msg":"Hi Eligald team,\n\nI'd like to discuss a Custom Blending project.\n\n• Chemical/product:\n• Required specification:\n• Volume needed:\n• Delivery location:\n\nCould you let me know if this is something you can help with, along with rough pricing and lead time? Thanks!"},
    {"id":"logistics-supply","title":"Logistics & Supply","icon":"fa-truck","tagline":"Cold-chain, hazmat, and bulk-liquid expertise.",
     "desc":"ADR-certified tankers and approved carriers for regional and international delivery of hazardous goods.",
     "bullets":["ADR/IMDG certified hazmat transport","Temperature-controlled options","Real-time shipment tracking","Import/export documentation","Scheduled replenishment contracts"],
     "wa_msg":"Hi Eligald team,\n\nI need help with logistics and supply for a chemical shipment.\n\n• Chemical/product:\n• Volume/weight:\n• Pickup location:\n• Delivery location:\n\nCould you share a quote and estimated delivery timeline? Thanks!"},
    {"id":"technical-consultation","title":"Technical Consultation","icon":"fa-microscope","tagline":"Expert guidance from application to compliance.",
     "desc":"Registered chemists provide on-site and remote support across chemical selection, process optimisation, and compliance.",
     "bullets":["Registered chemists and process engineers","On-site or remote consultation","REACH, EPA, GHS compliance audits","Process optimisation studies","Staff safety and handling training"],
     "wa_msg":"Hi Eligald team,\n\nI'm looking for technical consultation support.\n\n• Industry/sector:\n• Challenge or requirement:\n• Location:\n\nCould someone reach out to discuss how you can help? Thanks!"},
]

TEAM = []  # Cleared — leadership profiles are now managed by Admin → Team/Founders

# ─── Startup: init DB on gunicorn + local ─────────────────────────────────────
with app.app_context():
    try:
        init_db()
        import sqlite3 as _sqlite3
        from database import DB_PATH as _DB_PATH
        _conn = _sqlite3.connect(_DB_PATH)
        _conn.row_factory = _sqlite3.Row

        # PASS 1 — create any missing tables first (order matters for ALTERs below)
        for _sql in [
            """CREATE TABLE IF NOT EXISTS founders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                title TEXT DEFAULT '', bio TEXT DEFAULT '', photo_url TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')))""",
            """CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '', is_active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')))""",
            """CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                email TEXT DEFAULT '', phone TEXT DEFAULT '',
                source TEXT DEFAULT 'contact_form', marketing_consent INTEGER DEFAULT 0,
                notes TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')))""",
            """CREATE TABLE IF NOT EXISTS promotions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT DEFAULT '',
                message TEXT NOT NULL, channel TEXT DEFAULT 'email',
                recipient_filter TEXT DEFAULT 'all', status TEXT DEFAULT 'draft',
                sent_count INTEGER DEFAULT 0, created_by INTEGER,
                created_at TEXT DEFAULT (datetime('now')), sent_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS company_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT NOT NULL, label TEXT NOT NULL,
                icon TEXT DEFAULT 'fa-star', sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS whatsapp_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, phone TEXT NOT NULL,
                company TEXT DEFAULT '', source TEXT DEFAULT 'homepage_enquiry',
                created_at TEXT DEFAULT (datetime('now')))""",
            """CREATE TABLE IF NOT EXISTS testimonials (
                id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL,
                company TEXT DEFAULT '', quote TEXT NOT NULL, rating INTEGER DEFAULT 5,
                is_active INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')))""",
            """CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT 'Anonymous',
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                comment TEXT NOT NULL DEFAULT '',
                is_approved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')))""",
            """CREATE TABLE IF NOT EXISTS page_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                product_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')))""",
        ]:
            try: _conn.execute(_sql); _conn.commit()
            except Exception: pass

        # PASS 2 — now safe to ALTER, since all tables definitely exist
        for _sql in [
            "ALTER TABLE orders ADD COLUMN include_tax INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE site_settings ADD COLUMN founders_enabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE site_settings ADD COLUMN smtp_host TEXT DEFAULT 'smtp.gmail.com'",
            "ALTER TABLE site_settings ADD COLUMN smtp_port INTEGER DEFAULT 587",
            "ALTER TABLE site_settings ADD COLUMN email_sales TEXT DEFAULT ''",
            "ALTER TABLE site_settings ADD COLUMN email_general TEXT DEFAULT ''",
            "ALTER TABLE site_settings ADD COLUMN wa_auto_response_enabled INTEGER DEFAULT 0",
            "ALTER TABLE site_settings ADD COLUMN wa_auto_response_msg TEXT DEFAULT 'Hello {name}, thank you for contacting Eligald.'",
            "ALTER TABLE site_settings ADD COLUMN wa_business_token TEXT DEFAULT ''",
            "ALTER TABLE site_settings ADD COLUMN wa_phone_id TEXT DEFAULT ''",
            "ALTER TABLE site_settings ADD COLUMN team_visible INTEGER DEFAULT 0",
            "ALTER TABLE customers ADD COLUMN company TEXT DEFAULT ''",
            "ALTER TABLE founders ADD COLUMN linkedin_url TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN reset_token TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN reset_token_expires TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN whatsapp_number TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN two_factor_enabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN otp_code TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN otp_expires TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN otp_purpose TEXT DEFAULT ''",
            "ALTER TABLE products ADD COLUMN stock_quantity INTEGER DEFAULT NULL",
            "ALTER TABLE products ADD COLUMN low_stock_threshold INTEGER DEFAULT 10",
            "ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT ''",
            "ALTER TABLE orders ADD COLUMN amount_paid REAL DEFAULT 0",
            "ALTER TABLE orders ADD COLUMN payment_notes TEXT DEFAULT ''",
        ]:
            try: _conn.execute(_sql); _conn.commit()
            except Exception: pass
        # Seed the 16 real product categories if table is empty
        _existing = _conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if _existing == 0:
            _categories = [
                ("Agrochemicals", "Fertilizers and crop-care chemicals for agricultural applications.", 0),
                ("Animal Feeds and Veterinary Additives", "Feed-grade minerals, supplements and veterinary chemical additives.", 1),
                ("Basic Chemicals", "Core industrial acids, alkalis and solvents used across manufacturing.", 2),
                ("Construction Chemicals", "Additives for concrete, mortar, waterproofing and construction materials.", 3),
                ("Dyes and Colours", "Mordants, fixing agents and levelling chemicals for textile dyeing.", 4),
                ("Food and Beverage Processing Chemicals", "Food-grade acids, preservatives and processing aids.", 5),
                ("Industrial Acids and Bases", "Strong acids and alkalis for industrial neutralisation and processing.", 6),
                ("Industrial Solvents", "High-purity solvents for cleaning, coatings and chemical synthesis.", 7),
                ("Laboratory and Specialty Reagents", "Analytical-grade reagents for laboratory and research use.", 8),
                ("Paints, Ink and Coatings", "Solvents, resins, pigments and additives for paints and printing inks.", 9),
                ("Personal Care and Cosmetics Ingredients", "Cosmetic-grade surfactants, emollients and active ingredients.", 10),
                ("Petroleum Chemicals", "Chemicals for fuel blending, refining and oilfield operations.", 11),
                ("Plastics and Packaging Raw Materials", "Fillers, resins and additives for plastics and packaging manufacture.", 12),
                ("Soap and Detergents", "Surfactants, builders and alkalis for soap and detergent formulation.", 13),
                ("Textile, Rubber and Leather Processing", "Processing chemicals for textiles, rubber and leather industries.", 14),
                ("Water Treatments", "Coagulants, disinfectants and pH control chemicals for water treatment.", 15),
            ]
            for _name, _desc, _sort in _categories:
                try:
                    _conn.execute(
                        "INSERT OR IGNORE INTO categories (name, description, sort_order) VALUES (?,?,?)",
                        (_name, _desc, _sort)
                    )
                except Exception: pass
            _conn.commit()

        # Seed default company stats if empty
        _stats_existing = _conn.execute("SELECT COUNT(*) FROM company_stats").fetchone()[0]
        if _stats_existing == 0:
            _stats = [
                ("16", "Product Categories", "fa-flask", 1),
                ("177+", "Chemicals Supplied", "fa-vial", 2),
                ("500+", "Clients Served", "fa-handshake", 3),
                ("ISO", "Certified Quality", "fa-certificate", 4),
            ]
            for _num, _label, _icon, _sort in _stats:
                try:
                    _conn.execute(
                        "INSERT INTO company_stats (number,label,icon,sort_order) VALUES (?,?,?,?)",
                        (_num, _label, _icon, _sort)
                    )
                except Exception: pass
            _conn.commit()

        # One-time cleanup: remove the original 12 placeholder/demo products by exact name,
        # now superseded by the real 177-product catalogue below.
        _demo_names = [
            "Hydrochloric Acid 37%", "Acetone Industrial Grade", "Sodium Hydroxide Pellets",
            "Isopropyl Alcohol 99%", "Sulfuric Acid 98%", "Ethanol Absolute 99.8%",
            "Toluene Technical Grade", "Sodium Hypochlorite 12%", "Hydrogen Peroxide 50%",
            "Potassium Permanganate", "Methanol Technical Grade", "Ammonium Hydroxide 25%",
        ]
        for _dn in _demo_names:
            try:
                _conn.execute("DELETE FROM products WHERE name=?", (_dn,))
            except Exception:
                pass
        _conn.commit()

        # One-time: remove cross-category duplicate products, keeping only the
        # earliest-listed category occurrence for each unique product name.
        try:
            _dedup_done = _conn.execute(
                "SELECT COUNT(*) FROM activity_log WHERE action='PRODUCT_DEDUP_V1'"
            ).fetchone()[0]
        except Exception:
            _dedup_done = 0
        if not _dedup_done:
            _cat_order = [
                "Agrochemicals", "Animal Feeds and Veterinary Additives", "Basic Chemicals",
                "Construction Chemicals", "Dyes and Colours", "Food and Beverage Processing Chemicals",
                "Industrial Acids and Bases", "Industrial Solvents", "Laboratory and Specialty Reagents",
                "Paints, Ink and Coatings", "Personal Care and Cosmetics Ingredients", "Petroleum Chemicals",
                "Plastics and Packaging Raw Materials", "Soap and Detergents",
                "Textile, Rubber and Leather Processing", "Water Treatments",
            ]
            _cat_priority = {name: i for i, name in enumerate(_cat_order)}
            _all_prods = _conn.execute("SELECT id, name, category FROM products").fetchall()
            _by_name = {}
            for _row in _all_prods:
                _nm = _row["name"]
                if _nm not in _by_name:
                    _by_name[_nm] = _row
                else:
                    _cur = _by_name[_nm]
                    _cur_pri = _cat_priority.get(_cur["category"], 999)
                    _new_pri = _cat_priority.get(_row["category"], 999)
                    if _new_pri < _cur_pri:
                        _by_name[_nm] = _row
            _keep_ids = {r["id"] for r in _by_name.values()}
            _removed = 0
            for _row in _all_prods:
                if _row["id"] not in _keep_ids:
                    try:
                        _conn.execute("DELETE FROM products WHERE id=?", (_row["id"],))
                        _removed += 1
                    except Exception:
                        pass
            try:
                _conn.execute(
                    "INSERT INTO activity_log (username,action,details) VALUES ('system','PRODUCT_DEDUP_V1',?)",
                    (f"Removed {_removed} cross-category duplicate products",)
                )
            except Exception:
                pass
            _conn.commit()
            if _removed:
                print(f"[STARTUP] Deduplicated products: removed {_removed} cross-category duplicates")

        # One-time: update site address to the real warehouse location if it's still
        # the original placeholder or blank (never overwrites a custom address the admin set).
        try:
            _addr_row = _conn.execute("SELECT address FROM site_settings WHERE id=1").fetchone()
            _old_placeholders = {"", "123 Chemical Lane, Industrial City, IC 00000", "Nairobi, Kenya"}
            if _addr_row and (_addr_row[0] or "").strip() in _old_placeholders:
                _conn.execute(
                    "UPDATE site_settings SET address=? WHERE id=1",
                    ("Imara Daima, Along Enterprise Road, Opp SMK Business Centre, Nairobi, Kenya",)
                )
                _conn.commit()
                print("[STARTUP] Updated site address to warehouse location")
        except Exception as _addr_err:
            print(f"[STARTUP] Address update warning: {_addr_err}")

        # Seed the full 177-product catalogue (from official document).
        # Runs every startup but only inserts products that don't already exist (by name),
        # so it safely tops up an existing live database without duplicating anything.
        try:
            import json as _json
            _seed_path = os.path.join(os.path.dirname(__file__), "products_seed_data.json")
            with open(_seed_path, "r", encoding="utf-8") as _sf:
                _seed_products = _json.load(_sf)

            _existing_names = {row[0] for row in _conn.execute("SELECT name FROM products").fetchall()}

            # Backfill: give every existing product a distinct per-product image
            # (older deploys assigned one shared image per category — upgrade them here, once)
            try:
                _already_backfilled = _conn.execute(
                    "SELECT COUNT(*) FROM activity_log WHERE action='IMAGE_BACKFILL_V1'"
                ).fetchone()[0]
            except Exception:
                _already_backfilled = 0
            if not _already_backfilled:
                _existing_products = _conn.execute("SELECT id, name, category FROM products").fetchall()
                for _ep in _existing_products:
                    try:
                        _new_img = _product_image_for(_ep["name"], _ep["category"])
                        _conn.execute("UPDATE products SET image_url=? WHERE id=?", (_new_img, _ep["id"]))
                    except Exception:
                        pass
                try:
                    _conn.execute(
                        "INSERT INTO activity_log (username,action,details) VALUES ('system','IMAGE_BACKFILL_V1','Assigned distinct per-product images')"
                    )
                except Exception:
                    pass
                _conn.commit()
                print("[STARTUP] Backfilled distinct images for existing products")

            _inserted = 0
            for _sp in _seed_products:
                if _sp["name"] in _existing_names:
                    continue
                _specs_lines = [
                    f"Formula: {_sp['formula']}" if _sp.get('formula') else "",
                    f"CAS Number: {_sp['cas']}" if _sp.get('cas') else "",
                    f"Grade: {_sp['grade']}" if _sp.get('grade') else "",
                    f"Packaging: {_sp['packaging']}" if _sp.get('packaging') else "",
                    f"Safety: {_sp['safety']}" if _sp.get('safety') else "",
                ]
                _specs = "\n".join([l for l in _specs_lines if l])
                _desc  = _sp.get("overview", "")
                if _sp.get("application"):
                    _desc += f"\n\nApplication: {_sp['application']}"
                _img = _product_image_for(_sp["name"], _sp["category"])
                try:
                    _conn.execute(
                        "INSERT INTO products (name,description,specifications,image_url,category,is_active) "
                        "VALUES (?,?,?,?,?,1)",
                        (_sp["name"], _desc, _specs, _img, _sp["category"])
                    )
                    _inserted += 1
                except Exception:
                    pass
            _conn.commit()
            if _inserted:
                print(f"[STARTUP] Seeded {_inserted} new products from catalogue document")
        except Exception as _seed_err:
            print(f"[STARTUP] Product seed warning: {_seed_err}")

        _conn.close()
    except Exception as _e:
        print(f"[STARTUP] DB init warning: {_e}")

    # Start automated daily backups (persists to same volume as the DB)
    try:
        from backup import start_daily_backup_thread
        from database import DB_PATH as _BACKUP_DB_PATH
        start_daily_backup_thread(_BACKUP_DB_PATH)
    except Exception as _e:
        print(f"[BACKUP] Could not start backup thread: {_e}")

if __name__ == "__main__":
    _port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=_port, debug=False)
