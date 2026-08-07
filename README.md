# Eligald Industrial Chemicals – Flask Web App

A complete, production-ready Flask website for **Eligald Industrial Chemicals Limited**.

---

## Quick Start (macOS / MacBook Pro)

### 1. Create the project folder and virtual environment

```bash
cd ~/Desktop           # or wherever you want the project
# (the eligald_chemicals folder is already here if you cloned/unzipped it)
cd eligald_chemicals

python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the development server

```bash
flask --app app run --debug
```

The server starts at **http://127.0.0.1:5000** — open it in your browser.

> **Tip:** To use a custom port (e.g. 8080): `flask --app app run --debug --port 8080`

### 4. Run the test suite

In a separate terminal (with the venv still activated):

```bash
pytest test_app.py -v
```

All 16 tests should pass.

---

## Customising contact / WhatsApp details

Open `app.py` and edit the top section:

```python
WHATSAPP_NUMBER  = "15551234567"   # digits only, no + or spaces
EMAIL            = "info@eligaldchemicals.com"
PHONE            = "+1 (555) 123-4567"
ADDRESS          = "123 Chemical Lane, Industrial City, IC 00000"
```

Save and Flask's debug mode reloads the server automatically.

---

## Project structure

```
eligald_chemicals/
├── app.py                  # Flask app, all data, all routes
├── requirements.txt
├── test_app.py             # pytest smoke tests
├── static/
│   ├── css/style.css       # master stylesheet
│   └── js/main.js          # AOS init, search, scroll, newsletter
└── templates/
    ├── base.html           # sticky nav, footer, WA widget, back-to-top
    ├── index.html          # hero + particles.js, stats, why-us, featured products
    ├── about.html          # company profile, mission/vision, team
    ├── products.html       # filterable product grid
    ├── product_detail.html # full specs + WhatsApp order button
    ├── services.html       # 3 services with process steps
    ├── contact.html        # contact form + OpenStreetMap embed
    └── 404.html            # custom error page
```

---

## Features

- **Sticky navigation** with hover dropdowns (desktop) and Bootstrap toggle (mobile)
- **Hero section** with particles.js background and smooth animations
- **AOS scroll animations** throughout
- **Client-side product search** – instant filter by name/description/category
- **Category filter pills** – URL-based server-side filtering
- **WhatsApp ordering** on every product card, product detail page, and service card
- **Floating WhatsApp widget** with pulse animation on every page
- **Contact form** with validation and simulated submit (front-end demo)
- **Newsletter form** in footer with success toast
- **Back to Top** button
- **Fully responsive** – mobile-first, hamburger menu on small screens
- **SEO meta tags** and Open Graph tags in base template
- **Custom 404 page**
- **`prefers-reduced-motion`** respected in CSS
