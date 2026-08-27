"""
database.py – raw sqlite3 database layer for Eligald Industrial Chemicals.
Provides: init_db(), get_db(), and all model-level helper functions.
"""

import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, date
from contextlib import contextmanager

DB_DIR  = os.environ.get("DATA_DIR", os.path.dirname(__file__))
DB_PATH = os.path.join(DB_DIR, "eligald.db")
os.makedirs(DB_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Connection helpers
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_settings (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    company_name    TEXT    DEFAULT 'Eligald Industrial Chemicals Limited',
    logo_url        TEXT    DEFAULT '',
    address         TEXT    DEFAULT 'Imara Daima, Along Enterprise Road, Opp SMK Business Centre, Nairobi, Kenya',
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
    hero_subheading TEXT    DEFAULT 'Your trusted partner for solvents, acids, and specialty chemicals.'
);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'admin' CHECK(role IN ('super_admin','admin')),
    must_change_pw  INTEGER NOT NULL DEFAULT 0,
    email           TEXT    DEFAULT '',
    whatsapp_number TEXT    DEFAULT '',
    two_factor_enabled INTEGER NOT NULL DEFAULT 0,
    otp_code        TEXT    DEFAULT '',
    otp_expires     TEXT    DEFAULT '',
    otp_purpose     TEXT    DEFAULT '',
    reset_token     TEXT    DEFAULT '',
    reset_token_expires TEXT DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    specifications  TEXT    NOT NULL DEFAULT '',
    image_url       TEXT    NOT NULL DEFAULT '',
    category        TEXT    NOT NULL DEFAULT 'Specialty Chemicals',
    price_per_unit  REAL,
    stock_quantity  INTEGER DEFAULT NULL,
    low_stock_threshold INTEGER DEFAULT 10,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS leads (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name       TEXT    NOT NULL,
    phone_number        TEXT    NOT NULL,
    email               TEXT    DEFAULT '',
    product_id          INTEGER REFERENCES products(id) ON DELETE SET NULL,
    message             TEXT    DEFAULT '',
    status              TEXT    NOT NULL DEFAULT 'new' CHECK(status IN ('new','contacted','converted')),
    admin_notes         TEXT    DEFAULT '',
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
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
    payment_method  TEXT    DEFAULT '',
    amount_paid     REAL    DEFAULT 0,
    payment_notes   TEXT    DEFAULT '',
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


CREATE TABLE IF NOT EXISTS company_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL, label TEXT NOT NULL,
    icon TEXT DEFAULT 'fa-star', sort_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS whatsapp_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, phone TEXT NOT NULL,
    company TEXT DEFAULT '', source TEXT DEFAULT 'homepage_enquiry',
    created_at TEXT DEFAULT (datetime('now'))
);


CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL DEFAULT 'Anonymous',
    rating      INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    comment     TEXT    NOT NULL DEFAULT '',
    is_approved INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS page_views (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT    NOT NULL,
    product_id  INTEGER,
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
"""

# ─────────────────────────────────────────────────────────────────────────────
# Init / Seed
# ─────────────────────────────────────────────────────────────────────────────

def init_db():
    from werkzeug.security import generate_password_hash
    with db_conn() as conn:
        conn.executescript(SCHEMA)
        # Seed site settings (one row only)
        conn.execute(
            "INSERT OR IGNORE INTO site_settings (id) VALUES (1)"
        )
        # Seed super admin
        existing = conn.execute(
            "SELECT id FROM users WHERE username='Eligald'"
        ).fetchone()
        if not existing:
            ph = generate_password_hash("Kenya@254")
            conn.execute(
                "INSERT INTO users (username,password_hash,role,must_change_pw) VALUES (?,?,?,1)",
                ("Eligald", ph, "super_admin")
            )
        # Note: demo/placeholder products no longer auto-seeded here.
        # The real 177-product catalogue is seeded separately in app.py's startup
        # migration from products_seed_data.json.
    print(f"[DB] Initialised at {DB_PATH}")


def _seed_products(conn):
    products = [
        ("Hydrochloric Acid 37%", "ACS-grade fuming hydrochloric acid for industrial cleaning, pH adjustment, and metal pickling.", "Assay: 37% min (w/w)\nDensity: 1.19 g/mL\nUN Number: UN 1789\nPackaging: 25L carboys · 250L IBCs", "https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?w=600&q=80", "Acids & Bases", None),
        ("Acetone Industrial Grade", "Ultra-pure acetone for degreasing, coatings formulation, and pharmaceutical manufacturing.", "Purity: ≥99.5% (GC)\nWater Content: ≤0.1%\nFlash Point: -20°C\nUN Number: UN 1090", "https://images.unsplash.com/photo-1603126857599-f6e157fa2fe6?w=600&q=80", "Industrial Solvents", None),
        ("Sodium Hydroxide Pellets", "Technical-grade NaOH pellets for saponification, pulp processing, and wastewater treatment.", "Assay: ≥98% NaOH\nChloride: ≤0.005%\nUN Number: UN 1823\nPackaging: 25kg bags", "https://images.unsplash.com/photo-1614854262318-831574f15f1f?w=600&q=80", "Acids & Bases", None),
        ("Isopropyl Alcohol 99%", "Pharmaceutical-grade IPA for electronics cleaning, sanitisers, and extraction processes.", "Purity: ≥99.7% (GC)\nWater Content: ≤0.2%\nFlash Point: 12°C\nUN Number: UN 1219", "https://images.unsplash.com/photo-1616362787549-2b1a3b9b93dd?w=600&q=80", "Industrial Solvents", None),
        ("Sulfuric Acid 98%", "Concentrated H₂SO₄ for fertiliser manufacturing, metal treatment, and battery production.", "Assay: ≥98% H₂SO₄\nDensity: 1.84 g/mL\nUN Number: UN 1830\nPackaging: 25L carboys", "https://images.unsplash.com/photo-1628863353691-0071c8c1874c?w=600&q=80", "Acids & Bases", None),
        ("Ethanol Absolute 99.8%", "Anhydrous ethanol for analytical chemistry, HPLC mobile phases, and biotech applications.", "Purity: ≥99.8% (GC)\nWater Content: ≤0.02%\nFlash Point: 13°C\nUN Number: UN 1170", "https://images.unsplash.com/photo-1582719471137-c3967ffb1c42?w=600&q=80", "Laboratory Reagents", None),
        ("Toluene Technical Grade", "High-purity toluene for paint thinners, adhesive formulations, and chemical synthesis.", "Purity: ≥99.0% (GC)\nWater Content: ≤0.05%\nFlash Point: 4°C\nUN Number: UN 1294", "https://images.unsplash.com/photo-1576086213369-97a306d36557?w=600&q=80", "Industrial Solvents", None),
        ("Sodium Hypochlorite 12%", "Industrial bleach for water disinfection, textile bleaching, and surface sanitation.", "Active Chlorine: 11–13%\npH: 12–13\nUN Number: UN 1791\nPackaging: 25L · 200L", "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?w=600&q=80", "Specialty Chemicals", None),
        ("Hydrogen Peroxide 50%", "Technical-grade H₂O₂ for bleaching, oxidation reactions, and effluent treatment.", "Assay: 49–51% H₂O₂\nUN Number: UN 2014\nPackaging: 25kg · 250kg IBC", "https://images.unsplash.com/photo-1559757175-5700dde675bc?w=600&q=80", "Specialty Chemicals", None),
        ("Potassium Permanganate", "KMnO₄ crystals for water treatment, organic synthesis, and analytical chemistry.", "Assay: ≥99.0% KMnO₄\nAppearance: Dark purple-black crystals\nUN Number: UN 1490", "https://images.unsplash.com/photo-1605101100278-5d1deb2b6498?w=600&q=80", "Laboratory Reagents", None),
        ("Methanol Technical Grade", "High-purity methanol for biodiesel production, antifreeze formulation, and solvent uses.", "Purity: ≥99.85% (GC)\nFlash Point: 11°C\nUN Number: UN 1230\nPackaging: 20L · 200L", "https://images.unsplash.com/photo-1612817288484-6f916006741a?w=600&q=80", "Industrial Solvents", None),
        ("Ammonium Hydroxide 25%", "Technical-grade ammonia solution for fertilisers, pH control, and cleaning applications.", "Assay: 24–26% NH₃\nDensity: 0.91 g/mL\nUN Number: UN 2672\nPackaging: 25L · 250L IBC", "https://images.unsplash.com/photo-1587854692152-cbe660dbde88?w=600&q=80", "Specialty Chemicals", None),
    ]
    conn.executemany(
        "INSERT INTO products (name,description,specifications,image_url,category,price_per_unit) VALUES (?,?,?,?,?,?)",
        products
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper: next invoice number
# ─────────────────────────────────────────────────────────────────────────────

def next_invoice_number():
    with db_conn() as conn:
        row = conn.execute(
            "SELECT invoice_number FROM orders ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            try:
                n = int(row["invoice_number"].replace("INV-", "")) + 1
            except Exception:
                n = 1
        else:
            n = 1
        return f"INV-{n:04d}"


# ─────────────────────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────────────────────

def notify_all_admins(message, link=""):
    with db_conn() as conn:
        admins = conn.execute("SELECT id FROM users").fetchall()
        for a in admins:
            conn.execute(
                "INSERT INTO notifications (user_id,message,link) VALUES (?,?,?)",
                (a["id"], message, link)
            )


def notify_user(user_id, message, link=""):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO notifications (user_id,message,link) VALUES (?,?,?)",
            (user_id, message, link)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Activity log
# ─────────────────────────────────────────────────────────────────────────────

def log_action(user_id, username, action, details=""):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO activity_log (user_id,username,action,details) VALUES (?,?,?,?)",
            (user_id, username, action, details)
        )
