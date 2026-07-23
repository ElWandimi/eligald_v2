"""
test_app.py – basic smoke tests for Eligald Industrial Chemicals Flask app.
Run with:  pytest test_app.py -v
"""

import pytest
from app import app, PRODUCTS, SERVICES


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ─── Status codes ──────────────────────────────────────────────────────────

def test_home_loads(client):
    r = client.get("/")
    assert r.status_code == 200


def test_about_loads(client):
    r = client.get("/about")
    assert r.status_code == 200


def test_products_loads(client):
    r = client.get("/products")
    assert r.status_code == 200


def test_services_loads(client):
    r = client.get("/services")
    assert r.status_code == 200


def test_contact_loads(client):
    r = client.get("/contact")
    assert r.status_code == 200


def test_404_page(client):
    r = client.get("/this-does-not-exist")
    assert r.status_code == 404


# ─── Content checks ────────────────────────────────────────────────────────

def test_home_contains_company_name(client):
    r = client.get("/")
    assert b"Eligald" in r.data


def test_home_title_contains_eligald(client):
    r = client.get("/")
    assert b"Eligald" in r.data


def test_products_show_all_items(client):
    r = client.get("/products")
    for product in PRODUCTS:
        assert product["name"].encode() in r.data


def test_product_category_filter(client):
    r = client.get("/products?category=Acids+%26+Bases")
    assert r.status_code == 200
    assert b"Hydrochloric Acid" in r.data


def test_product_detail_valid_id(client):
    r = client.get("/products/1")
    assert r.status_code == 200
    assert b"Hydrochloric Acid 37%" in r.data


def test_product_detail_invalid_id(client):
    r = client.get("/products/9999")
    assert r.status_code == 404


def test_product_detail_contains_specs(client):
    r = client.get("/products/1")
    assert b"Technical Specifications" in r.data


def test_services_page_contains_all_services(client):
    r = client.get("/services")
    for service in SERVICES:
        # Jinja2 auto-escapes '&' as '&amp;' in HTML output
        title_html  = service["title"].replace("&", "&amp;").encode()
        title_plain = service["title"].encode()
        assert title_html in r.data or title_plain in r.data


def test_whatsapp_links_present_on_home(client):
    r = client.get("/")
    assert b"wa.me" in r.data


def test_contact_page_contains_email(client):
    r = client.get("/contact")
    assert b"info@eligaldchemicals.com" in r.data


def test_footer_present_on_all_pages(client):
    for url in ["/", "/about", "/products", "/services", "/contact"]:
        r = client.get(url)
        assert b"main-footer" in r.data, f"Footer missing on {url}"


def test_nav_present_on_all_pages(client):
    for url in ["/", "/about", "/products", "/services", "/contact"]:
        r = client.get(url)
        assert b"main-nav" in r.data, f"Nav missing on {url}"
