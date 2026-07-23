"""
database.py – SQLite database layer for Eligald Industrial Chemicals.
Includes full schema, seed data, and helper functions.
"""
import sqlite3, hashlib, secrets, os
from datetime import datetime, date
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "eligald.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def db_conn():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_settings (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    company_name    TEXT    DEFAULT 'Eligald Industrial Chemicals Limited',
    logo_url        TEXT    DEFAULT '',
    address         TEXT    DEFAULT '123 Chemical Lane, Industrial City, IC 00000',
    phone           TEXT    DEFAULT '+254 719 655 694',
    whatsapp_number TEXT    DEFAULT '254719655694',
    email           TEXT    DEFAULT 'eligald.chemicals26@gmail.com',
    about_us_text   TEXT    DEFAULT '',
    mission_text    TEXT    DEFAULT '',
    vision_text     TEXT    DEFAULT '',
    facebook_url    TEXT    DEFAULT '',
    linkedin_url    TEXT    DEFAULT '',
    twitter_url     TEXT    DEFAULT '',
    hero_tagline    TEXT    DEFAULT 'Premium Industrial Chemicals, Delivered with Precision',
    hero_subheading TEXT    DEFAULT 'Your trusted partner for solvents, acids, and specialty chemicals.',
    founders_enabled INTEGER NOT NULL DEFAULT 0,
    smtp_user       TEXT    DEFAULT '',
    smtp_pass       TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'admin' CHECK(role IN ('super_admin','admin')),
    must_change_pw  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_address  TEXT    NOT NULL,
    username    TEXT    NOT NULL DEFAULT '',
    success     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    specifications  TEXT    NOT NULL DEFAULT '',
    image_url       TEXT    NOT NULL DEFAULT '',
    sds_url         TEXT    NOT NULL DEFAULT '',
    category        TEXT    NOT NULL DEFAULT 'Specialty Chemicals',
    price_per_unit  REAL,
    min_order_qty   TEXT    NOT NULL DEFAULT '',
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS testimonials (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT    NOT NULL,
    company       TEXT    NOT NULL DEFAULT '',
    quote         TEXT    NOT NULL,
    rating        INTEGER NOT NULL DEFAULT 5,
    is_active     INTEGER NOT NULL DEFAULT 1,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name   TEXT    NOT NULL,
    phone_number    TEXT    NOT NULL,
    email           TEXT    DEFAULT '',
    product_id      INTEGER REFERENCES products(id) ON DELETE SET NULL,
    message         TEXT    DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'new' CHECK(status IN ('new','contacted','converted')),
    admin_notes     TEXT    DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id         INTEGER REFERENCES leads(id) ON DELETE SET NULL,
    customer_name   TEXT    NOT NULL,
    customer_email  TEXT    NOT NULL DEFAULT '',
    customer_phone  TEXT    NOT NULL DEFAULT '',
    billing_address TEXT    NOT NULL DEFAULT '',
    invoice_number  TEXT    NOT NULL UNIQUE,
    issued_date     TEXT    NOT NULL DEFAULT (date('now')),
    due_date        TEXT    NOT NULL DEFAULT (date('now','+30 days')),
    status          TEXT    NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','sent','paid','cancelled')),
    include_tax     INTEGER NOT NULL DEFAULT 1,
    notes           TEXT    DEFAULT '',
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INTEGER REFERENCES products(id) ON DELETE SET NULL,
    description TEXT    NOT NULL DEFAULT '',
    quantity    REAL    NOT NULL DEFAULT 1,
    unit        TEXT    NOT NULL DEFAULT 'unit',
    unit_price  REAL    NOT NULL DEFAULT 0,
    total_price REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL,
    subject     TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','closed')),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ticket_replies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    message     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message     TEXT    NOT NULL,
    link        TEXT    NOT NULL DEFAULT '',
    is_read     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);


CREATE TABLE IF NOT EXISTS founders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    title       TEXT    NOT NULL DEFAULT '',
    bio         TEXT    NOT NULL DEFAULT '',
    photo_url   TEXT    NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username    TEXT    NOT NULL DEFAULT '',
    action      TEXT    NOT NULL,
    details     TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_products_category    ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_active      ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_leads_status         ON leads(status);
CREATE INDEX IF NOT EXISTS idx_orders_status        ON orders(status);
CREATE INDEX IF NOT EXISTS idx_tickets_status       ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_notifications_user   ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip    ON login_attempts(ip_address, created_at);
"""

def init_db():
    from werkzeug.security import generate_password_hash
    with db_conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO site_settings (id) VALUES (1)")
        existing = conn.execute("SELECT id FROM users WHERE username='Eligald'").fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO users (username,password_hash,role,must_change_pw) VALUES (?,?,?,0)",
                ("Eligald", generate_password_hash("Kenya@254"), "super_admin")
            )
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            _seed_products(conn)
        if conn.execute("SELECT COUNT(*) FROM testimonials").fetchone()[0] == 0:
            _seed_testimonials(conn)
    print(f"[DB] Initialised → {DB_PATH}")

def _seed_products(conn):
    products = [
        ("Hydrochloric Acid 37%","ACS-grade fuming HCl for industrial cleaning, pH adjustment, and metal pickling.","Assay: 37% min (w/w)\nDensity: 1.19 g/mL\nFlash Point: N/A\nUN Number: UN 1789\nPackaging: 25L carboys · 250L IBCs","https://picsum.photos/seed/hcl/600/400","Acids & Bases",None,"25L minimum"),
        ("Acetone Industrial Grade","Ultra-pure acetone for degreasing, coatings, and pharmaceutical manufacturing.","Purity: ≥99.5% (GC)\nWater Content: ≤0.1%\nFlash Point: -20°C\nUN Number: UN 1090\nPackaging: 20L · 200L drums","https://picsum.photos/seed/acetone/600/400","Industrial Solvents",None,"20L minimum"),
        ("Sodium Hydroxide Pellets","Technical-grade NaOH for saponification, pulp processing, and wastewater treatment.","Assay: ≥98% NaOH\nChloride: ≤0.005%\nUN Number: UN 1823\nPackaging: 25kg bags · 1000kg supersacks","https://picsum.photos/seed/naoh/600/400","Acids & Bases",None,"25kg minimum"),
        ("Isopropyl Alcohol 99%","Pharmaceutical-grade IPA for electronics cleaning, sanitisers, and extraction.","Purity: ≥99.7% (GC)\nWater Content: ≤0.2%\nFlash Point: 12°C\nUN Number: UN 1219\nPackaging: 5L · 25L · 200L","https://picsum.photos/seed/ipa/600/400","Industrial Solvents",None,"5L minimum"),
        ("Sulfuric Acid 98%","Concentrated H₂SO₄ for fertiliser manufacturing, metal treatment, and batteries.","Assay: ≥98% H₂SO₄\nDensity: 1.84 g/mL\nUN Number: UN 1830\nPackaging: 25L carboys","https://picsum.photos/seed/h2so4/600/400","Acids & Bases",None,"25L minimum"),
        ("Ethanol Absolute 99.8%","Anhydrous ethanol for analytical chemistry, HPLC mobile phases, and biotech.","Purity: ≥99.8% (GC)\nWater Content: ≤0.02%\nFlash Point: 13°C\nUN Number: UN 1170","https://picsum.photos/seed/ethanol/600/400","Laboratory Reagents",None,"2.5L minimum"),
        ("Toluene Technical Grade","High-purity toluene for paint thinners, adhesive formulations, and synthesis.","Purity: ≥99.0% (GC)\nWater Content: ≤0.05%\nFlash Point: 4°C\nUN Number: UN 1294","https://picsum.photos/seed/toluene/600/400","Industrial Solvents",None,"20L minimum"),
        ("Sodium Hypochlorite 12%","Industrial bleach for water disinfection, textile bleaching, and sanitation.","Active Chlorine: 11–13%\npH: 12–13\nUN Number: UN 1791\nPackaging: 25L · 200L","https://picsum.photos/seed/hypochlorite/600/400","Specialty Chemicals",None,"25L minimum"),
        ("Hydrogen Peroxide 50%","Technical-grade H₂O₂ for bleaching, oxidation reactions, and effluent treatment.","Assay: 49–51% H₂O₂\nUN Number: UN 2014\nPackaging: 25kg · 250kg IBC","https://picsum.photos/seed/h2o2/600/400","Specialty Chemicals",None,"25kg minimum"),
        ("Potassium Permanganate","KMnO₄ crystals for water treatment, organic synthesis, and analytical chemistry.","Assay: ≥99.0% KMnO₄\nAppearance: Dark purple-black crystals\nUN Number: UN 1490","https://picsum.photos/seed/kmno4/600/400","Laboratory Reagents",None,"25kg minimum"),
        ("Methanol Technical Grade","High-purity methanol for biodiesel production, antifreeze, and solvent use.","Purity: ≥99.85% (GC)\nFlash Point: 11°C\nUN Number: UN 1230\nPackaging: 20L · 200L drums","https://picsum.photos/seed/methanol/600/400","Industrial Solvents",None,"20L minimum"),
        ("Ammonium Hydroxide 25%","Technical-grade ammonia solution for fertilisers, pH control, and cleaning.","Assay: 24–26% NH₃\nDensity: 0.91 g/mL\nUN Number: UN 2672\nPackaging: 25L · 250L IBC","https://picsum.photos/seed/ammonia/600/400","Specialty Chemicals",None,"25L minimum"),
    ]
    conn.executemany(
        "INSERT INTO products (name,description,specifications,image_url,category,price_per_unit,min_order_qty) VALUES (?,?,?,?,?,?,?)",
        products
    )

def _seed_testimonials(conn):
    testimonials = [
        ("Dr. James Mwangi","Nairobi Water & Sewerage Co.","Eligald has been our go-to supplier for water treatment chemicals for over 5 years. Consistent quality, on-time delivery, and their technical team is always available.",5,1),
        ("Sarah Otieno","Kenya Breweries Ltd","The ethanol and IPA quality from Eligald is exceptional. Every batch comes with a full CoA and the pricing is competitive. Highly recommended.",5,2),
        ("Eng. Peter Kamau","East African Refineries","Their logistics team handled our bulk sulfuric acid shipment flawlessly — all ADR documentation, on-time, zero incidents. Professional from start to finish.",5,3),
    ]
    conn.executemany(
        "INSERT INTO testimonials (customer_name,company,quote,rating,sort_order) VALUES (?,?,?,?,?)",
        testimonials
    )

def next_invoice_number():
    with db_conn() as conn:
        row = conn.execute("SELECT invoice_number FROM orders ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            try: n = int(row["invoice_number"].replace("INV-","")) + 1
            except: n = 1
        else: n = 1
        return f"INV-{n:04d}"

def notify_all_admins(message, link=""):
    with db_conn() as conn:
        admins = conn.execute("SELECT id FROM users").fetchall()
        for a in admins:
            conn.execute("INSERT INTO notifications (user_id,message,link) VALUES (?,?,?)",
                         (a["id"], message, link))

def notify_user(user_id, message, link=""):
    with db_conn() as conn:
        conn.execute("INSERT INTO notifications (user_id,message,link) VALUES (?,?,?)",
                     (user_id, message, link))

def log_action(user_id, username, action, details=""):
    with db_conn() as conn:
        conn.execute("INSERT INTO activity_log (user_id,username,action,details) VALUES (?,?,?,?)",
                     (user_id, username, action, details))

def record_login_attempt(ip, username, success):
    with db_conn() as conn:
        conn.execute("INSERT INTO login_attempts (ip_address,username,success) VALUES (?,?,?)",
                     (ip, username, 1 if success else 0))
        # Clean old attempts (older than 1 hour)
        conn.execute("DELETE FROM login_attempts WHERE created_at < datetime('now','-1 hour')")

def count_failed_attempts(ip, window_minutes=15):
    db  = get_db()
    row = db.execute(
        "SELECT COUNT(*) FROM login_attempts WHERE ip_address=? AND success=0 "
        "AND created_at > datetime('now',?)",
        (ip, f"-{window_minutes} minutes")
    ).fetchone()
    db.close()
    return row[0] if row else 0
