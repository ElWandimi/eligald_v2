"""
blueprints/admin.py – Full admin panel with rate limiting & account lockout.
"""
import os, csv, io, json, secrets, re
from datetime import datetime, date
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, g, flash, jsonify, send_file, abort, current_app
)
from werkzeug.security  import generate_password_hash, check_password_hash
from werkzeug.utils     import secure_filename

from database   import (
    get_db, db_conn, next_invoice_number,
    notify_all_admins, notify_user, log_action, DB_PATH,
    record_login_attempt, count_failed_attempts
)
from auth       import login_user, logout_user, login_required, super_admin_required
from pdf_generator import generate_invoice_pdf
from rate_limit import check_rate_limit, rate_limit_response

admin_bp = Blueprint("admin_bp", __name__, template_folder="../templates/admin")
ALLOWED  = {"png","jpg","jpeg","gif","webp"}

def allowed_file(fn):
    return "." in fn and fn.rsplit(".",1)[1].lower() in ALLOWED

def save_upload(file, subfolder):
    fn  = secure_filename(file.filename)
    ext = fn.rsplit(".",1)[-1].lower()
    if ext not in ALLOWED: return ""
    unique = f"{secrets.token_hex(8)}.{ext}"
    dest   = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder, unique)
    file.save(dest)
    return f"/static/uploads/{subfolder}/{unique}"

# ─── LOGIN / LOGOUT ──────────────────────────────────────────────────────────

@admin_bp.route("/login", methods=["GET","POST"])
def login():
    if g.get("user"):
        return redirect(url_for("admin_bp.dashboard"))
    error = None
    if request.method == "POST":
        ip       = request.remote_addr or "unknown"
        username = request.form.get("username","").strip()
        password = request.form.get("password","")

        # Rate limit: 10 login attempts per 15 minutes
        if not check_rate_limit("login", limit=10, window=900):
            return render_template("admin/login.html",
                error="Too many login attempts. Please wait 15 minutes.")

        # Account lockout: 5 failed attempts per 15 minutes
        failed = count_failed_attempts(ip, window_minutes=15)
        if failed >= 5:
            return render_template("admin/login.html",
                error="Account temporarily locked after too many failed attempts. Try again in 15 minutes.")

        db   = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        db.close()

        if user and check_password_hash(user["password_hash"], password):
            record_login_attempt(ip, username, True)
            login_user(user["id"])
            log_action(user["id"], user["username"], "LOGIN", f"IP: {ip}")
            if user["must_change_pw"]:
                flash("Please change your password before continuing.", "warning")
                return redirect(url_for("admin_bp.change_password"))
            return redirect(url_for("admin_bp.dashboard"))
        else:
            record_login_attempt(ip, username, False)
            error = "Invalid username or password."

    return render_template("admin/login.html", error=error)


@admin_bp.route("/logout")
def logout():
    if g.get("user"):
        log_action(g.user["id"], g.user["username"], "LOGOUT")
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("admin_bp.login"))


@admin_bp.route("/change-password", methods=["GET","POST"])
@login_required
def change_password():
    error = None
    if request.method == "POST":
        current = request.form.get("current_password","")
        new_pw  = request.form.get("new_password","")
        confirm = request.form.get("confirm_password","")
        if new_pw != confirm:
            error = "New passwords do not match."
        elif len(new_pw) < 8:
            error = "Password must be at least 8 characters."
        else:
            db   = get_db()
            user = db.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
            db.close()
            if not check_password_hash(user["password_hash"], current):
                error = "Current password is incorrect."
            else:
                with db_conn() as conn:
                    conn.execute(
                        "UPDATE users SET password_hash=?,must_change_pw=0 WHERE id=?",
                        (generate_password_hash(new_pw), g.user["id"])
                    )
                log_action(g.user["id"], g.user["username"], "CHANGE_PASSWORD")
                flash("Password updated successfully.", "success")
                return redirect(url_for("admin_bp.dashboard"))
    return render_template("admin/change_password.html", error=error)

# ─── DASHBOARD ───────────────────────────────────────────────────────────────

@admin_bp.route("/")
@login_required
def dashboard():
    db = get_db()
    total_products = db.execute("SELECT COUNT(*) FROM products WHERE is_active=1").fetchone()[0]
    pending_orders = db.execute("SELECT COUNT(*) FROM orders WHERE status IN ('draft','sent')").fetchone()[0]
    open_tickets   = db.execute("SELECT COUNT(*) FROM tickets WHERE status!='closed'").fetchone()[0]
    unread_notifs  = db.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (g.user["id"],)
    ).fetchone()[0]
    # Revenue KPI
    revenue_row = db.execute(
        "SELECT COALESCE(SUM(oi.total_price),0) AS rev FROM order_items oi "
        "JOIN orders o ON oi.order_id=o.id WHERE o.status='paid'"
    ).fetchone()
    total_revenue = revenue_row["rev"] if revenue_row else 0
    # Overdue orders
    overdue = db.execute(
        "SELECT COUNT(*) FROM orders WHERE status='sent' AND due_date < date('now')"
    ).fetchone()[0]
    recent_leads   = db.execute(
        "SELECT l.*, p.name AS product_name FROM leads l "
        "LEFT JOIN products p ON l.product_id=p.id ORDER BY l.created_at DESC LIMIT 6"
    ).fetchall()
    recent_tickets = db.execute("SELECT * FROM tickets ORDER BY created_at DESC LIMIT 6").fetchall()
    # Charts
    order_stats  = db.execute("SELECT status, COUNT(*) as cnt FROM orders GROUP BY status").fetchall()
    chart_labels = [r["status"].title() for r in order_stats]
    chart_data   = [r["cnt"] for r in order_stats]
    leads_monthly= db.execute("""
        SELECT strftime('%Y-%m',created_at) as month, COUNT(*) as cnt
        FROM leads WHERE created_at >= date('now','-6 months')
        GROUP BY month ORDER BY month
    """).fetchall()
    lead_months = [r["month"] for r in leads_monthly]
    lead_counts = [r["cnt"]   for r in leads_monthly]
    # Revenue monthly
    rev_monthly = db.execute("""
        SELECT strftime('%Y-%m',o.created_at) as month,
               COALESCE(SUM(oi.total_price),0) as rev
        FROM orders o JOIN order_items oi ON oi.order_id=o.id
        WHERE o.status='paid' AND o.created_at >= date('now','-6 months')
        GROUP BY month ORDER BY month
    """).fetchall()
    rev_months = [r["month"] for r in rev_monthly]
    rev_vals   = [r["rev"]   for r in rev_monthly]
    db.close()
    return render_template("admin/dashboard.html",
        total_products=total_products, pending_orders=pending_orders,
        open_tickets=open_tickets, unread_notifs=unread_notifs,
        total_revenue=total_revenue, overdue=overdue,
        recent_leads=recent_leads, recent_tickets=recent_tickets,
        chart_labels=json.dumps(chart_labels), chart_data=json.dumps(chart_data),
        lead_months=json.dumps(lead_months), lead_counts=json.dumps(lead_counts),
        rev_months=json.dumps(rev_months), rev_vals=json.dumps(rev_vals),
    )

# ─── PRODUCTS ────────────────────────────────────────────────────────────────
CATEGORIES = ["Industrial Solvents","Acids & Bases","Specialty Chemicals","Laboratory Reagents"]

@admin_bp.route("/products")
@login_required
def products():
    db  = get_db()
    q   = request.args.get("q","").strip()
    cat = request.args.get("category","All")
    qry = "SELECT * FROM products WHERE 1=1"
    params = []
    if q:   qry += " AND (name LIKE ? OR description LIKE ?)"; params += [f"%{q}%",f"%{q}%"]
    if cat != "All": qry += " AND category=?"; params.append(cat)
    qry += " ORDER BY name"
    prods = db.execute(qry, params).fetchall()
    db.close()
    return render_template("admin/products.html", products=prods,
                           categories=CATEGORIES, q=q, active_cat=cat)

@admin_bp.route("/products/new", methods=["GET","POST"])
@login_required
def product_new():
    if request.method == "POST":
        name    = request.form.get("name","").strip()
        desc    = request.form.get("description","").strip()
        specs   = request.form.get("specifications","").strip()
        cat     = request.form.get("category","Specialty Chemicals")
        price   = request.form.get("price_per_unit","") or None
        minqty  = request.form.get("min_order_qty","").strip()
        active  = 1 if request.form.get("is_active") else 0
        img_url = request.form.get("image_url","").strip()
        sds_url = request.form.get("sds_url","").strip()
        if not name:
            flash("Product name is required.","danger")
            return render_template("admin/product_form.html", product=None, categories=CATEGORIES)
        if "image_file" in request.files:
            f = request.files["image_file"]
            if f and f.filename and allowed_file(f.filename):
                img_url = save_upload(f,"products")
        with db_conn() as conn:
            cur = conn.execute(
                "INSERT INTO products (name,description,specifications,image_url,sds_url,category,price_per_unit,min_order_qty,is_active) VALUES (?,?,?,?,?,?,?,?,?)",
                (name,desc,specs,img_url,sds_url,cat,price,minqty,active)
            )
            pid = cur.lastrowid
        log_action(g.user["id"],g.user["username"],"PRODUCT_CREATE",f"#{pid}: {name}")
        flash(f"Product '{name}' created.","success")
        return redirect(url_for("admin_bp.products"))
    return render_template("admin/product_form.html", product=None, categories=CATEGORIES)

@admin_bp.route("/products/<int:pid>/edit", methods=["GET","POST"])
@login_required
def product_edit(pid):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    db.close()
    if not product: abort(404)
    if request.method == "POST":
        name    = request.form.get("name","").strip()
        desc    = request.form.get("description","").strip()
        specs   = request.form.get("specifications","").strip()
        cat     = request.form.get("category","Specialty Chemicals")
        price   = request.form.get("price_per_unit","") or None
        minqty  = request.form.get("min_order_qty","").strip()
        active  = 1 if request.form.get("is_active") else 0
        img_url = request.form.get("image_url", product["image_url"])
        sds_url = request.form.get("sds_url", product["sds_url"] if "sds_url" in product.keys() else "")
        if "image_file" in request.files:
            f = request.files["image_file"]
            if f and f.filename and allowed_file(f.filename): img_url = save_upload(f,"products")
        with db_conn() as conn:
            conn.execute(
                "UPDATE products SET name=?,description=?,specifications=?,image_url=?,sds_url=?,"
                "category=?,price_per_unit=?,min_order_qty=?,is_active=?,updated_at=datetime('now') WHERE id=?",
                (name,desc,specs,img_url,sds_url,cat,price,minqty,active,pid)
            )
        log_action(g.user["id"],g.user["username"],"PRODUCT_EDIT",f"#{pid}: {name}")
        flash(f"Product '{name}' updated.","success")
        return redirect(url_for("admin_bp.products"))
    return render_template("admin/product_form.html", product=dict(product), categories=CATEGORIES)

@admin_bp.route("/products/<int:pid>/delete", methods=["POST"])
@login_required
def product_delete(pid):
    db = get_db()
    p  = db.execute("SELECT name FROM products WHERE id=?",(pid,)).fetchone()
    db.close()
    if p:
        with db_conn() as conn: conn.execute("DELETE FROM products WHERE id=?",(pid,))
        log_action(g.user["id"],g.user["username"],"PRODUCT_DELETE",f"#{pid}: {p['name']}")
        flash(f"Product '{p['name']}' deleted.","success")
    return redirect(url_for("admin_bp.products"))

@admin_bp.route("/products/<int:pid>/toggle", methods=["POST"])
@login_required
def product_toggle(pid):
    with db_conn() as conn:
        conn.execute("UPDATE products SET is_active=CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",(pid,))
    return redirect(url_for("admin_bp.products"))

# ─── LEADS ───────────────────────────────────────────────────────────────────

@admin_bp.route("/leads")
@login_required
def leads():
    db     = get_db()
    status = request.args.get("status","All")
    q      = request.args.get("q","").strip()
    qry    = "SELECT l.*, p.name AS product_name FROM leads l LEFT JOIN products p ON l.product_id=p.id WHERE 1=1"
    params = []
    if status != "All": qry += " AND l.status=?"; params.append(status)
    if q: qry += " AND (l.customer_name LIKE ? OR l.phone_number LIKE ?)"; params += [f"%{q}%",f"%{q}%"]
    qry += " ORDER BY l.created_at DESC"
    all_leads= db.execute(qry,params).fetchall()
    products = db.execute("SELECT id,name FROM products WHERE is_active=1 ORDER BY name").fetchall()
    db.close()
    return render_template("admin/leads.html", leads=all_leads,
                           products=products, active_status=status, q=q)

@admin_bp.route("/leads/new", methods=["GET","POST"])
@login_required
def lead_new():
    db = get_db()
    products = db.execute("SELECT id,name FROM products WHERE is_active=1 ORDER BY name").fetchall()
    db.close()
    if request.method == "POST":
        cname = request.form.get("customer_name","").strip()
        phone = request.form.get("phone_number","").strip()
        email = request.form.get("email","").strip()
        pid   = request.form.get("product_id") or None
        msg   = request.form.get("message","").strip()
        if not cname or not phone:
            flash("Customer name and phone are required.","danger")
            return render_template("admin/lead_form.html", products=products, lead=None)
        with db_conn() as conn:
            conn.execute("INSERT INTO leads (customer_name,phone_number,email,product_id,message) VALUES (?,?,?,?,?)",
                         (cname,phone,email,pid,msg))
        log_action(g.user["id"],g.user["username"],"LEAD_CREATE",f"New lead: {cname}")
        flash("Lead added.","success")
        return redirect(url_for("admin_bp.leads"))
    return render_template("admin/lead_form.html", products=products, lead=None)

@admin_bp.route("/leads/<int:lid>", methods=["GET","POST"])
@login_required
def lead_detail(lid):
    db   = get_db()
    lead = db.execute("SELECT l.*, p.name AS product_name FROM leads l LEFT JOIN products p ON l.product_id=p.id WHERE l.id=?",(lid,)).fetchone()
    products = db.execute("SELECT id,name FROM products WHERE is_active=1 ORDER BY name").fetchall()
    db.close()
    if not lead: abort(404)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update":
            notes  = request.form.get("admin_notes","")
            status = request.form.get("status", lead["status"])
            with db_conn() as conn:
                conn.execute("UPDATE leads SET admin_notes=?,status=?,updated_at=datetime('now') WHERE id=?",(notes,status,lid))
            flash("Lead updated.","success")
        elif action == "convert":
            return redirect(url_for("admin_bp.order_new", lead_id=lid))
        return redirect(url_for("admin_bp.lead_detail", lid=lid))
    return render_template("admin/lead_detail.html", lead=dict(lead), products=products)

# ─── ORDERS ──────────────────────────────────────────────────────────────────

@admin_bp.route("/orders")
@login_required
def orders():
    db     = get_db()
    status = request.args.get("status","All")
    q      = request.args.get("q","").strip()
    qry    = "SELECT * FROM orders WHERE 1=1"
    params = []
    if status != "All": qry += " AND status=?"; params.append(status)
    if q: qry += " AND (customer_name LIKE ? OR invoice_number LIKE ?)"; params += [f"%{q}%",f"%{q}%"]
    qry += " ORDER BY created_at DESC"
    all_orders = db.execute(qry,params).fetchall()
    today = date.today().isoformat()
    totals = {}
    for o in all_orders:
        row = db.execute("SELECT COALESCE(SUM(total_price),0) AS tot FROM order_items WHERE order_id=?",(o["id"],)).fetchone()
        totals[o["id"]] = row["tot"]
    db.close()
    return render_template("admin/orders.html", orders=all_orders, totals=totals,
                           active_status=status, q=q, today=today)

@admin_bp.route("/orders/new", methods=["GET","POST"])
@login_required
def order_new():
    lead_id = request.args.get("lead_id")
    prefill = {}
    if lead_id:
        db   = get_db()
        lead = db.execute("SELECT * FROM leads WHERE id=?",(lead_id,)).fetchone()
        db.close()
        if lead: prefill = dict(lead)
    db       = get_db()
    products = db.execute("SELECT id,name FROM products WHERE is_active=1 ORDER BY name").fetchall()
    db.close()
    if request.method == "POST":
        cname   = request.form.get("customer_name","").strip()
        cemail  = request.form.get("customer_email","").strip()
        cphone  = request.form.get("customer_phone","").strip()
        billing = request.form.get("billing_address","").strip()
        due     = request.form.get("due_date", str(date.today()))
        notes   = request.form.get("notes","")
        lid     = request.form.get("lead_id") or None
        descs       = request.form.getlist("item_description[]")
        qtys        = request.form.getlist("item_quantity[]")
        units       = request.form.getlist("item_unit[]")
        unit_prices = request.form.getlist("item_unit_price[]")
        pids        = request.form.getlist("item_product_id[]")
        include_tax = 1 if request.form.get("include_tax") else 0
        inv_num = next_invoice_number()
        with db_conn() as conn:
            cur = conn.execute(
                "INSERT INTO orders (lead_id,customer_name,customer_email,customer_phone,"
                "billing_address,invoice_number,due_date,include_tax,notes,created_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (lid,cname,cemail,cphone,billing,inv_num,due,include_tax,notes,g.user["id"])
            )
            oid = cur.lastrowid
            for i,desc in enumerate(descs):
                if not desc.strip(): continue
                qty   = float(qtys[i])        if i < len(qtys)        else 1
                up    = float(unit_prices[i]) if i < len(unit_prices) else 0
                conn.execute(
                    "INSERT INTO order_items (order_id,product_id,description,quantity,unit,unit_price,total_price) VALUES (?,?,?,?,?,?,?)",
                    (oid, pids[i] if i < len(pids) and pids[i] else None,
                     desc.strip(), qty, units[i] if i < len(units) else "unit", up, qty*up)
                )
            if lid:
                conn.execute("UPDATE leads SET status='converted',updated_at=datetime('now') WHERE id=?",(lid,))
        log_action(g.user["id"],g.user["username"],"ORDER_CREATE",f"Created {inv_num}")
        flash(f"Order {inv_num} created.","success")
        return redirect(url_for("admin_bp.order_detail", oid=oid))
    from datetime import date, timedelta
    today    = date.today()
    due_date = (today + timedelta(days=30)).isoformat()
    return render_template("admin/order_form.html", products=products, prefill=prefill,
                           lead_id=lead_id, today=today.isoformat(), default_due=due_date)

@admin_bp.route("/orders/<int:oid>")
@login_required
def order_detail(oid):
    db    = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
    if not order: db.close(); abort(404)
    items = db.execute("SELECT oi.*, p.name AS product_name FROM order_items oi LEFT JOIN products p ON oi.product_id=p.id WHERE oi.order_id=?",(oid,)).fetchall()
    total = sum(i["total_price"] for i in items)
    today = date.today().isoformat()
    db.close()
    return render_template("admin/order_detail.html", order=dict(order), items=items, total=total, today=today)

@admin_bp.route("/orders/<int:oid>/status", methods=["POST"])
@login_required
def order_status(oid):
    new_status = request.form.get("status")
    if new_status in ("draft","sent","paid","cancelled"):
        with db_conn() as conn:
            conn.execute("UPDATE orders SET status=?,updated_at=datetime('now') WHERE id=?",(new_status,oid))
        if new_status == "paid":
            db = get_db()
            o  = db.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
            db.close()
            if o and o["created_by"]:
                notify_user(o["created_by"], f"Order {o['invoice_number']} marked as PAID.", f"/admin/orders/{oid}")
        log_action(g.user["id"],g.user["username"],"ORDER_STATUS",f"#{oid} → {new_status}")
        flash(f"Order status updated to {new_status}.","success")
    return redirect(url_for("admin_bp.order_detail", oid=oid))

@admin_bp.route("/orders/<int:oid>/pdf")
@login_required
def order_pdf(oid):
    try:
        db    = get_db()
        order = db.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
        if not order: db.close(); abort(404)
        items    = db.execute("SELECT * FROM order_items WHERE order_id=?",(oid,)).fetchall()
        settings = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
        db.close()

        settings_dict = dict(settings) if settings else {}
        order_dict    = dict(order)

        # Safe tax check - column may not exist on older DB
        try:
            include_tax = bool(order["include_tax"])
        except Exception:
            include_tax = True

        pdf_bytes = generate_invoice_pdf(
            order_dict, [dict(i) for i in items],
            settings_dict, include_tax=include_tax
        )
        with db_conn() as conn:
            conn.execute(
                "UPDATE orders SET status='sent',updated_at=datetime('now') WHERE id=? AND status='draft'",
                (oid,)
            )
        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        return send_file(buf, mimetype="application/pdf", as_attachment=True,
                         download_name=f"{order_dict['invoice_number']}.pdf")
    except Exception as e:
        import traceback
        current_app.logger.error(f"PDF generation error for order {oid}: {traceback.format_exc()}")
        flash(f"PDF generation failed: {str(e)}", "danger")
        return redirect(url_for("admin_bp.order_detail", oid=oid))

@admin_bp.route("/orders/export-csv")
@login_required
def orders_csv():
    db = get_db()
    all_orders = db.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    totals = {}
    for o in all_orders:
        row = db.execute("SELECT COALESCE(SUM(total_price),0) AS tot FROM order_items WHERE order_id=?",(o["id"],)).fetchone()
        totals[o["id"]] = row["tot"]
    db.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Invoice #","Customer","Email","Phone","Status","Total (KES)","Issued","Due"])
    for o in all_orders:
        writer.writerow([o["invoice_number"],o["customer_name"],o["customer_email"],
                         o["customer_phone"],o["status"],f"{totals[o['id']]:.2f}",
                         o["issued_date"],o["due_date"]])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype="text/csv",
                     as_attachment=True, download_name="eligald_orders.csv")

# ─── TICKETS ─────────────────────────────────────────────────────────────────

@admin_bp.route("/tickets")
@login_required
def tickets():
    db     = get_db()
    status = request.args.get("status","All")
    q      = request.args.get("q","").strip()
    qry    = "SELECT * FROM tickets WHERE 1=1"
    params = []
    if status != "All": qry += " AND status=?"; params.append(status)
    if q: qry += " AND (subject LIKE ? OR name LIKE ?)"; params += [f"%{q}%",f"%{q}%"]
    qry += " ORDER BY created_at DESC"
    all_tickets = db.execute(qry,params).fetchall()
    db.close()
    return render_template("admin/tickets.html", tickets=all_tickets, active_status=status, q=q)

@admin_bp.route("/tickets/<int:tid>", methods=["GET","POST"])
@login_required
def ticket_detail(tid):
    db     = get_db()
    ticket = db.execute("SELECT * FROM tickets WHERE id=?",(tid,)).fetchone()
    if not ticket: db.close(); abort(404)
    replies= db.execute("SELECT tr.*, u.username FROM ticket_replies tr LEFT JOIN users u ON tr.user_id=u.id WHERE tr.ticket_id=? ORDER BY tr.created_at",(tid,)).fetchall()
    db.close()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "reply":
            msg = request.form.get("message","").strip()
            if msg:
                with db_conn() as conn:
                    conn.execute("INSERT INTO ticket_replies (ticket_id,user_id,message) VALUES (?,?,?)",(tid,g.user["id"],msg))
                    conn.execute("UPDATE tickets SET status='in_progress',updated_at=datetime('now') WHERE id=? AND status='open'",(tid,))
                flash("Reply added.","success")
        elif action == "status":
            new_st = request.form.get("status")
            if new_st in ("open","in_progress","closed"):
                with db_conn() as conn:
                    conn.execute("UPDATE tickets SET status=?,updated_at=datetime('now') WHERE id=?",(new_st,tid))
                log_action(g.user["id"],g.user["username"],"TICKET_STATUS",f"#{tid} → {new_st}")
                flash(f"Ticket status changed to {new_st}.","success")
        return redirect(url_for("admin_bp.ticket_detail", tid=tid))
    return render_template("admin/ticket_detail.html", ticket=dict(ticket), replies=replies)

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
        rating = int(request.form.get("rating",5))
        sort   = int(request.form.get("sort_order",0))
        active = 1 if request.form.get("is_active") else 0
        if not cname or not quote:
            flash("Name and quote are required.","danger")
            return render_template("admin/testimonial_form.html", t=None)
        with db_conn() as conn:
            conn.execute("INSERT INTO testimonials (customer_name,company,quote,rating,sort_order,is_active) VALUES (?,?,?,?,?,?)",
                         (cname,company,quote,rating,sort,active))
        flash("Testimonial added.","success")
        return redirect(url_for("admin_bp.testimonials"))
    return render_template("admin/testimonial_form.html", t=None)

@admin_bp.route("/testimonials/<int:tid>/edit", methods=["GET","POST"])
@login_required
def testimonial_edit(tid):
    db = get_db()
    t  = db.execute("SELECT * FROM testimonials WHERE id=?",(tid,)).fetchone()
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
        flash("Testimonial updated.","success")
        return redirect(url_for("admin_bp.testimonials"))
    return render_template("admin/testimonial_form.html", t=dict(t))

@admin_bp.route("/testimonials/<int:tid>/delete", methods=["POST"])
@login_required
def testimonial_delete(tid):
    with db_conn() as conn: conn.execute("DELETE FROM testimonials WHERE id=?",(tid,))
    flash("Testimonial deleted.","success")
    return redirect(url_for("admin_bp.testimonials"))

# ─── NOTIFICATIONS ────────────────────────────────────────────────────────────

@admin_bp.route("/notifications")
@login_required
def notifications():
    db    = get_db()
    notifs= db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",(g.user["id"],)).fetchall()
    db.close()
    return render_template("admin/notifications.html", notifications=notifs)

@admin_bp.route("/notifications/unread-count")
@login_required
def notif_unread_count():
    db  = get_db()
    cnt = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",(g.user["id"],)).fetchone()[0]
    db.close()
    return jsonify({"count": cnt})

@admin_bp.route("/notifications/preview")
@login_required
def notif_preview():
    db    = get_db()
    notifs= db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 5",(g.user["id"],)).fetchall()
    db.close()
    return jsonify({"notifications":[dict(n) for n in notifs]})

@admin_bp.route("/notifications/<int:nid>/read")
@login_required
def notif_read(nid):
    db    = get_db()
    notif = db.execute("SELECT * FROM notifications WHERE id=? AND user_id=?",(nid,g.user["id"])).fetchone()
    db.close()
    if notif:
        with db_conn() as conn: conn.execute("UPDATE notifications SET is_read=1 WHERE id=?",(nid,))
        if notif["link"]: return redirect(notif["link"])
    return redirect(url_for("admin_bp.notifications"))

@admin_bp.route("/notifications/mark-all-read", methods=["POST"])
@login_required
def notif_mark_all_read():
    with db_conn() as conn: conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(g.user["id"],))
    return redirect(url_for("admin_bp.notifications"))

# ─── SETTINGS ────────────────────────────────────────────────────────────────

@admin_bp.route("/settings", methods=["GET","POST"])
@super_admin_required
def settings():
    db  = get_db()
    row = db.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    db.close()
    if request.method == "POST":
        fields = ["company_name","address","phone","whatsapp_number","email",
                  "about_us_text","mission_text","vision_text",
                  "facebook_url","linkedin_url","twitter_url",
                  "hero_tagline","hero_subheading","smtp_user","smtp_pass"]
        values = {f: request.form.get(f,"").strip() for f in fields}
        # Checkbox field - not in form data when unchecked
        values["founders_enabled"] = 1 if request.form.get("founders_enabled") else 0
        logo_url = dict(row).get("logo_url","") if row else ""
        if "logo_file" in request.files:
            lf = request.files["logo_file"]
            if lf and lf.filename and allowed_file(lf.filename):
                logo_url = save_upload(lf,"logos")
        values["logo_url"] = logo_url
        set_clause = ", ".join(f"{k}=?" for k in values)
        with db_conn() as conn:
            conn.execute(f"UPDATE site_settings SET {set_clause} WHERE id=1", list(values.values()))
        log_action(g.user["id"],g.user["username"],"SETTINGS_UPDATE","Updated site settings")
        flash("Site settings saved.","success")
        return redirect(url_for("admin_bp.settings"))
    return render_template("admin/settings.html", s=dict(row) if row else {})

# ─── USERS ───────────────────────────────────────────────────────────────────

@admin_bp.route("/users")
@super_admin_required
def users():
    db = get_db()
    all_users = db.execute("SELECT * FROM users ORDER BY created_at").fetchall()
    db.close()
    return render_template("admin/users.html", users=all_users)

@admin_bp.route("/users/new", methods=["GET","POST"])
@super_admin_required
def user_new():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        role     = request.form.get("role","admin")
        if not username or not password:
            flash("Username and password are required.","danger")
            return render_template("admin/user_form.html", user=None)
        db = get_db()
        if db.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone():
            db.close(); flash("Username already taken.","danger")
            return render_template("admin/user_form.html", user=None)
        db.close()
        with db_conn() as conn:
            conn.execute("INSERT INTO users (username,password_hash,role,must_change_pw) VALUES (?,?,?,1)",
                         (username,generate_password_hash(password),role))
        log_action(g.user["id"],g.user["username"],"USER_CREATE",f"{username} ({role})")
        flash(f"User '{username}' created.","success")
        return redirect(url_for("admin_bp.users"))
    return render_template("admin/user_form.html", user=None)

@admin_bp.route("/users/<int:uid>/edit", methods=["GET","POST"])
@super_admin_required
def user_edit(uid):
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    db.close()
    if not user: abort(404)
    if request.method == "POST":
        role     = request.form.get("role","admin")
        password = request.form.get("password","").strip()
        with db_conn() as conn:
            conn.execute("UPDATE users SET role=? WHERE id=?",(role,uid))
            if password:
                conn.execute("UPDATE users SET password_hash=?,must_change_pw=0 WHERE id=?",
                             (generate_password_hash(password),uid))
        log_action(g.user["id"],g.user["username"],"USER_EDIT",f"#{uid}")
        flash("User updated.","success")
        return redirect(url_for("admin_bp.users"))
    return render_template("admin/user_form.html", user=dict(user))

@admin_bp.route("/users/<int:uid>/delete", methods=["POST"])
@super_admin_required
def user_delete(uid):
    if uid == g.user["id"]:
        flash("You cannot delete your own account.","danger")
        return redirect(url_for("admin_bp.users"))
    db   = get_db()
    user = db.execute("SELECT username FROM users WHERE id=?",(uid,)).fetchone()
    db.close()
    if user:
        with db_conn() as conn: conn.execute("DELETE FROM users WHERE id=?",(uid,))
        log_action(g.user["id"],g.user["username"],"USER_DELETE",f"{user['username']}")
        flash(f"User '{user['username']}' deleted.","success")
    return redirect(url_for("admin_bp.users"))

# ─── ACTIVITY LOG ─────────────────────────────────────────────────────────────

@admin_bp.route("/activity-log")
@super_admin_required
def activity_log():
    db   = get_db()
    logs = db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 200").fetchall()
    db.close()
    return render_template("admin/activity_log.html", logs=logs)

# ─── BACKUP ───────────────────────────────────────────────────────────────────

@admin_bp.route("/backup")
@super_admin_required
def backup():
    log_action(g.user["id"],g.user["username"],"DB_BACKUP","Downloaded database backup")
    return send_file(DB_PATH, as_attachment=True,
                     download_name=f"eligald_backup_{date.today()}.db",
                     mimetype="application/x-sqlite3")

# ─── FOUNDERS (Super Admin only) ──────────────────────────────────────────────

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
        conn.execute(
            "UPDATE site_settings SET founders_enabled = CASE WHEN founders_enabled=1 THEN 0 ELSE 1 END WHERE id=1"
        )
    log_action(g.user["id"], g.user["username"], "FOUNDERS_TOGGLE", "Toggled founders page visibility")
    flash("Founders page visibility updated.", "success")
    return redirect(url_for("admin_bp.founders"))


@admin_bp.route("/founders/new", methods=["GET", "POST"])
@super_admin_required
def founder_new():
    if request.method == "POST":
        name      = request.form.get("name", "").strip()
        title     = request.form.get("title", "").strip()
        bio       = request.form.get("bio", "").strip()
        sort      = int(request.form.get("sort_order", 0))
        active    = 1 if request.form.get("is_active") else 0
        photo_url = request.form.get("photo_url", "").strip()
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
        log_action(g.user["id"], g.user["username"], "FOUNDER_CREATE", f"Added founder: {name}")
        flash(f"Founder '{name}' added.", "success")
        return redirect(url_for("admin_bp.founders"))
    return render_template("admin/founder_form.html", founder=None)


@admin_bp.route("/founders/<int:fid>/edit", methods=["GET", "POST"])
@super_admin_required
def founder_edit(fid):
    db      = get_db()
    founder = db.execute("SELECT * FROM founders WHERE id=?", (fid,)).fetchone()
    db.close()
    if not founder: abort(404)
    if request.method == "POST":
        name      = request.form.get("name", "").strip()
        title     = request.form.get("title", "").strip()
        bio       = request.form.get("bio", "").strip()
        sort      = int(request.form.get("sort_order", 0))
        active    = 1 if request.form.get("is_active") else 0
        photo_url = request.form.get("photo_url", founder["photo_url"])
        if "photo_file" in request.files:
            f = request.files["photo_file"]
            if f and f.filename and allowed_file(f.filename):
                photo_url = save_upload(f, "products")
        with db_conn() as conn:
            conn.execute(
                "UPDATE founders SET name=?,title=?,bio=?,photo_url=?,sort_order=?,is_active=? WHERE id=?",
                (name, title, bio, photo_url, sort, active, fid)
            )
        log_action(g.user["id"], g.user["username"], "FOUNDER_EDIT", f"Edited founder #{fid}")
        flash("Founder updated.", "success")
        return redirect(url_for("admin_bp.founders"))
    return render_template("admin/founder_form.html", founder=dict(founder))


@admin_bp.route("/founders/<int:fid>/delete", methods=["POST"])
@super_admin_required
def founder_delete(fid):
    with db_conn() as conn:
        conn.execute("DELETE FROM founders WHERE id=?", (fid,))
    log_action(g.user["id"], g.user["username"], "FOUNDER_DELETE", f"Deleted founder #{fid}")
    flash("Founder deleted.", "success")
    return redirect(url_for("admin_bp.founders"))
