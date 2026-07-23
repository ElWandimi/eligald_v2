# Eligald Industrial Chemicals Limited – Web Platform

A production-ready Flask web application for Eligald Industrial Chemicals Limited.

## Features

### Public Site
- Dynamic product catalogue (DB-driven, searchable, filterable)
- WhatsApp enquiry modal on every product
- Customer testimonials section
- Contact form → creates support ticket
- SEO: sitemap.xml, robots.txt, JSON-LD structured data, OG tags
- Cookie consent banner
- Privacy Policy & Terms of Service pages
- Fallback product images

### Admin Panel (`/admin`)
- **Dashboard** – KPIs: products, revenue, overdue invoices, tickets; Chart.js charts
- **Products** – add/edit/delete, image upload, SDS upload, toggle active
- **Leads** – WhatsApp CRM, convert to order
- **Orders & Invoicing** – create orders, generate PDF invoices (ReportLab), export CSV
- **Tickets** – support thread view, admin replies
- **Testimonials** – manage site testimonials
- **Notifications** – real-time bell with 30s polling
- **Site Settings** – live edit WhatsApp number, tagline, company info, SMTP
- **Admin Users** – create/edit/delete (Super Admin only)
- **Activity Log** – audit trail
- **DB Backup** – one-click SQLite download

### Security
- CSRF protection on all POST forms
- Rate limiting (login: 10/15min, contact: 5/10min)
- Account lockout after 5 failed login attempts per 15 minutes
- Security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options
- Secure session cookies (HttpOnly, SameSite=Lax)
- Input validation and sanitisation
- Parameterised SQL queries throughout
- `.well-known/security.txt`

## Quick Start (macOS)

```bash
# 1. Enter project folder
cd eligald_chemicals

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install flask reportlab werkzeug

# 4. Initialise database
python3 -c "from database import init_db; init_db()"

# 5. Run (port 8080 avoids macOS AirPlay conflict)
flask --app app run --debug --port 8080
```

Open **http://127.0.0.1:8080** (public site) and **http://127.0.0.1:8080/admin** (admin panel).

**Default login:** `Eligald` / `Kenya@254`

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | Flask session secret | (hardcoded dev key) |
| `FLASK_ENV` | `development` or `production` | `development` |

Copy `.env.example` to `.env` and set values before deploying.

## Project Structure

```
eligald_chemicals/
├── app.py                  # Main Flask app, routes, security headers
├── auth.py                 # Session-based authentication
├── csrf.py                 # CSRF token generation & validation
├── rate_limit.py           # In-memory rate limiter
├── database.py             # SQLite schema, seeds, helpers
├── pdf_generator.py        # ReportLab PDF invoice generator
├── blueprints/
│   └── admin.py            # All admin routes (500+ lines)
├── templates/
│   ├── base.html           # Shared layout: nav, footer, cookie banner
│   ├── index.html          # Home page
│   ├── products.html       # Product listing with WA modal
│   ├── product_detail.html # Product detail with related products
│   ├── about.html          # About page
│   ├── services.html       # Services page
│   ├── contact.html        # Contact form
│   ├── privacy.html        # Privacy Policy
│   ├── terms.html          # Terms of Service
│   ├── sitemap.xml         # Dynamic XML sitemap
│   ├── 404.html            # Custom 404 page
│   ├── error.html          # Generic error page (400/403/429/500)
│   └── admin/              # Admin panel templates
├── static/
│   ├── css/style.css       # Public site styles
│   ├── css/admin.css       # Admin panel styles
│   ├── js/main.js          # Public JS
│   ├── js/admin.js         # Admin JS (sidebar, notifications, charts)
│   └── images/             # Static assets incl. fallback SVG
├── .env.example
├── .gitignore
├── requirements.txt
└── test_app.py
```

## Production Deployment Checklist

- [ ] Set a strong `SECRET_KEY` environment variable
- [ ] Set `FLASK_ENV=production`
- [ ] Use a production WSGI server: `gunicorn -w 4 app:app`
- [ ] Put behind Nginx (handle HTTPS, static files)
- [ ] Set up automated DB backups (use Admin → DB Backup or cron)
- [ ] Replace sample contact details in Site Settings
- [ ] Configure Gmail App Password in Site Settings for email invoices
- [ ] Submit sitemap to Google Search Console

## Running Tests

```bash
pytest test_app.py -v
```
