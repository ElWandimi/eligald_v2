"""
pdf_generator.py – Professional ReportLab invoice generator for Eligald.
Features:
  - Company logo in header (top-left)
  - Watermark logo (semi-transparent, centred on page)
  - Professional header with clean separator
  - Company details footer
  - Tax inclusion/exclusion toggle
"""

import io, os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, Image, KeepTogether
)
from reportlab.lib.utils import ImageReader

# ── Brand colours ─────────────────────────────────────────────────────────────
GREEN_DARK  = colors.HexColor("#1B5E20")
GREEN_MID   = colors.HexColor("#2E7D32")
GREEN_LIGHT = colors.HexColor("#C8E6C9")
GREEN_PALE  = colors.HexColor("#F1F8E9")
GREEN_ACCENT= colors.HexColor("#4CAF50")
CHARCOAL    = colors.HexColor("#2D2D2D")
GREY        = colors.HexColor("#757575")
GREY_LIGHT  = colors.HexColor("#EEEEEE")
WHITE       = colors.white

LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "images", "logo.png")
TAX_RATE  = 0.16  # 16% VAT


def _watermark(canvas, doc):
    """Draw semi-transparent logo watermark on every page. Safe - never crashes."""
    try:
        if not os.path.exists(LOGO_PATH):
            return
        canvas.saveState()
        canvas.setFillAlpha(0.06)
        w, h = A4
        img_w, img_h = 160*mm, 160*mm
        x = (w - img_w) / 2
        y = (h - img_h) / 2
        canvas.drawImage(
            LOGO_PATH, x, y, width=img_w, height=img_h,
            preserveAspectRatio=True, mask='auto'
        )
        canvas.restoreState()
    except Exception:
        try:
            canvas.restoreState()
        except Exception:
            pass


def generate_invoice_pdf(order, items, settings, include_tax=None):
    """
    order       – dict with order fields
    items       – list of dicts (description, quantity, unit, unit_price, total_price)
    settings    – dict with site_settings fields
    include_tax – bool override; if None uses order['include_tax']
    Returns bytes (PDF content)
    """
    buffer = io.BytesIO()

    # Tax decision
    if include_tax is None:
        include_tax = bool(order.get("include_tax", 1))

    # Try to get logo from URL in settings if local file missing
    global LOGO_PATH
    _logo_url = settings.get("logo_url", "")
    if not os.path.exists(LOGO_PATH) and _logo_url and _logo_url.startswith("http"):
        try:
            import urllib.request
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            urllib.request.urlretrieve(_logo_url, tmp.name)
            LOGO_PATH = tmp.name
        except Exception:
            pass

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16*mm, leftMargin=16*mm,
        topMargin=14*mm,   bottomMargin=20*mm,
    )

    co_name  = settings.get("company_name",    "Eligald Industrial Chemicals Limited")
    co_addr  = settings.get("address",         "123 Chemical Lane, Industrial City")
    co_phone = settings.get("phone",           "+254 719 655 694")
    co_email = settings.get("email",           "eligald.chemicals26@gmail.com")
    co_wa    = settings.get("whatsapp_number", "254719655694")

    story = []

    # ── HEADER: Logo + Company info + Invoice label ───────────────────────────
    # Logo in header - safe fallback if file missing
    logo_cell = Paragraph(
        "<font color='#1B5E20'><b>⚗ Eligald</b></font>",
        ParagraphStyle("li", fontSize=14, textColor=GREEN_DARK,
                       fontName="Helvetica-Bold")
    )
    if os.path.exists(LOGO_PATH):
        try:
            logo_img = Image(LOGO_PATH, width=38*mm, height=38*mm)
            logo_img.hAlign = "LEFT"
            logo_cell = logo_img
        except Exception:
            pass  # Keep text fallback

    co_style = ParagraphStyle(
        "co", fontSize=8, leading=13, textColor=CHARCOAL,
        fontName="Helvetica"
    )
    co_bold = ParagraphStyle(
        "cob", fontSize=10, leading=14, textColor=GREEN_DARK,
        fontName="Helvetica-Bold"
    )
    inv_style = ParagraphStyle(
        "inv", fontSize=26, textColor=GREEN_DARK,
        fontName="Helvetica-Bold", alignment=TA_RIGHT
    )
    inv_meta = ParagraphStyle(
        "im", fontSize=8, leading=13, textColor=GREY,
        fontName="Helvetica", alignment=TA_RIGHT
    )

    status_colour = {
        "draft":     "#9E9E9E",
        "sent":      "#1565C0",
        "paid":      "#1B5E20",
        "cancelled": "#B71C1C",
    }.get(order.get("status","draft"), "#9E9E9E")

    header_data = [[
        # Left: logo
        logo_cell,
        # Centre: company details
        [
            Paragraph(co_name, co_bold),
            Paragraph(co_addr, co_style),
            Paragraph(f"Tel: {co_phone}", co_style),
            Paragraph(f"Email: {co_email}", co_style),
            Paragraph(f"WhatsApp: +{co_wa}", co_style),
        ],
        # Right: INVOICE label + meta
        [
            Paragraph("INVOICE", inv_style),
            Spacer(1, 3*mm),
            Paragraph(
                f"<b>No:</b> {order['invoice_number']}<br/>"
                f"<b>Date:</b> {order['issued_date']}<br/>"
                f"<b>Due:</b> {order['due_date']}<br/>"
                f"<font color='{status_colour}'><b>{order.get('status','').upper()}</b></font>",
                inv_meta
            ),
        ],
    ]]

    header_tbl = Table(header_data, colWidths=[40*mm, 80*mm, 58*mm])
    header_tbl.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("BACKGROUND",   (0,0), (-1,-1), GREEN_PALE),
        ("ROWPADDING",   (0,0), (-1,-1), 8),
        ("LEFTPADDING",  (0,0), (0,-1),  6),
        ("RIGHTPADDING", (-1,0),(-1,-1), 6),
        ("LINEBELOW",    (0,0), (-1,-1), 2.5, GREEN_MID),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 5*mm))

    # ── BILL-TO ───────────────────────────────────────────────────────────────
    bt_label = ParagraphStyle(
        "btl", fontSize=7, textColor=WHITE, fontName="Helvetica-Bold",
        leftPadding=6, spaceBefore=2
    )
    bt_body = ParagraphStyle(
        "btb", fontSize=8.5, leading=13, textColor=CHARCOAL,
        fontName="Helvetica", leftPadding=6
    )

    bill_to_data = [[
        Paragraph("BILL TO", bt_label),
        Paragraph("INVOICE DETAILS", bt_label),
    ],[
        Paragraph(
            f"<b>{order['customer_name']}</b><br/>"
            f"{order.get('customer_email','')}<br/>"
            f"{order.get('customer_phone','')}<br/>"
            f"{order.get('billing_address','')}",
            bt_body
        ),
        Paragraph(
            f"<b>Invoice #:</b>  {order['invoice_number']}<br/>"
            f"<b>Issued:</b>     {order['issued_date']}<br/>"
            f"<b>Due Date:</b>   {order['due_date']}<br/>"
            f"<b>Tax:</b>        {'16% VAT Included' if include_tax else 'No Tax / Tax Exempt'}",
            bt_body
        ),
    ]]
    bill_tbl = Table(bill_to_data, colWidths=[89*mm, 89*mm])
    bill_tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,0), GREEN_DARK),
        ("TEXTCOLOR",   (0,0), (-1,0), WHITE),
        ("BACKGROUND",  (0,1), (-1,-1), WHITE),
        ("BOX",         (0,0), (-1,-1), 0.5, GREEN_LIGHT),
        ("LINEAFTER",   (0,0), (0,-1),  0.5, GREEN_LIGHT),
        ("ROWPADDING",  (0,0), (-1,-1), 5),
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
    ]))
    story.append(bill_tbl)
    story.append(Spacer(1, 6*mm))

    # ── ITEMS TABLE ────────────────────────────────────────────────────────────
    col_heads = ["#", "Description", "Qty", "Unit", "Unit Price (KES)", "Total (KES)"]
    rows = [col_heads]
    subtotal = 0.0
    for i, it in enumerate(items, 1):
        rows.append([
            str(i),
            it.get("description", ""),
            f"{float(it.get('quantity',1)):.2f}",
            it.get("unit", ""),
            f"{float(it.get('unit_price',0)):,.2f}",
            f"{float(it.get('total_price',0)):,.2f}",
        ])
        subtotal += float(it.get("total_price", 0))

    tax_amt = subtotal * TAX_RATE if include_tax else 0.0
    total   = subtotal + tax_amt

    # Totals rows
    rows.append(["", "", "", "", "Subtotal", f"{subtotal:,.2f}"])
    if include_tax:
        rows.append(["", "", "", "", f"VAT ({int(TAX_RATE*100)}%)", f"{tax_amt:,.2f}"])
    rows.append(["", "", "", "", "TOTAL DUE", f"KES {total:,.2f}"])

    n = len(rows)
    col_w = [8*mm, 62*mm, 14*mm, 14*mm, 32*mm, 28*mm]

    items_tbl = Table(rows, colWidths=col_w, repeatRows=1)
    total_rows_back = 3 if include_tax else 2

    ts = [
        # Header row
        ("BACKGROUND",  (0,0),  (-1,0),    GREEN_DARK),
        ("TEXTCOLOR",   (0,0),  (-1,0),    WHITE),
        ("FONTNAME",    (0,0),  (-1,0),    "Helvetica-Bold"),
        ("FONTSIZE",    (0,0),  (-1,0),    8),
        # Data rows alternating
        ("ROWBACKGROUNDS", (0,1), (-1, n-total_rows_back-1), [WHITE, GREEN_PALE]),
        ("FONTSIZE",    (0,1),  (-1,-1),   8),
        ("TEXTCOLOR",   (0,1),  (-1,-1),   CHARCOAL),
        # Subtotals
        ("BACKGROUND",  (4, n-total_rows_back), (-1, n-2), GREEN_PALE),
        ("FONTNAME",    (4, n-total_rows_back), (-1, n-2), "Helvetica-Bold"),
        # TOTAL row
        ("BACKGROUND",  (4, n-1), (-1, n-1), GREEN_DARK),
        ("TEXTCOLOR",   (4, n-1), (-1, n-1), WHITE),
        ("FONTNAME",    (4, n-1), (-1, n-1), "Helvetica-Bold"),
        ("FONTSIZE",    (4, n-1), (-1, n-1), 9),
        # Grid
        ("GRID",        (0,0),  (-1, n-total_rows_back-1), 0.4, GREEN_LIGHT),
        ("LINEABOVE",   (0, n-total_rows_back), (-1, n-1), 0.8, GREEN_MID),
        # Alignment
        ("ALIGN",       (2,0),  (-1,-1),   "RIGHT"),
        ("ALIGN",       (0,0),  (0,-1),    "CENTER"),
        ("VALIGN",      (0,0),  (-1,-1),   "MIDDLE"),
        ("ROWPADDING",  (0,0),  (-1,-1),   5),
    ]
    items_tbl.setStyle(TableStyle(ts))
    story.append(items_tbl)
    story.append(Spacer(1, 5*mm))

    # ── NOTES ─────────────────────────────────────────────────────────────────
    if order.get("notes"):
        story.append(Paragraph(
            f"<b>Notes:</b> {order['notes']}",
            ParagraphStyle("notes", fontSize=8, textColor=GREY, leading=12, fontName="Helvetica")
        ))
        story.append(Spacer(1, 4*mm))

    # ── PAYMENT INSTRUCTIONS ──────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREEN_LIGHT))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        f"<b><font color='#2E7D32'>Payment Instructions</font></b><br/>"
        f"M-Pesa Paybill / Bank transfer details provided on request.<br/>"
        f"Queries: {co_email}  |  WhatsApp: +{co_wa}",
        ParagraphStyle("pay", fontSize=8, leading=12, textColor=CHARCOAL, fontName="Helvetica")
    ))
    story.append(Spacer(1, 6*mm))

    # ── FOOTER: Company details horizontal bar ─────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1.5, color=GREEN_MID))
    story.append(Spacer(1, 2*mm))

    footer_style = ParagraphStyle(
        "ft", fontSize=7.5, textColor=CHARCOAL,
        fontName="Helvetica", alignment=TA_CENTER, leading=11
    )
    footer_data = [[
        Paragraph(f"<b>{co_name}</b>", footer_style),
        Paragraph(f"📍 {co_addr}", footer_style),
        Paragraph(f"📞 {co_phone}", footer_style),
        Paragraph(f"✉ {co_email}", footer_style),
        Paragraph(f"💬 +{co_wa}", footer_style),
    ]]
    footer_tbl = Table(footer_data, colWidths=[48*mm, 42*mm, 34*mm, 38*mm, 26*mm])
    footer_tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,-1), GREEN_PALE),
        ("ROWPADDING",  (0,0), (-1,-1), 5),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("FONTSIZE",    (0,0), (-1,-1), 7),
        ("LINEAFTER",   (0,0), (-2,-1), 0.3, GREEN_LIGHT),
    ]))
    story.append(footer_tbl)
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "<font color='#9E9E9E' size='6.5'>This invoice was generated by Eligald Industrial Chemicals Limited. "
        "All prices in KES unless otherwise stated. Thank you for your business.</font>",
        ParagraphStyle("disc", fontSize=6.5, textColor=GREY, alignment=TA_CENTER,
                       fontName="Helvetica")
    ))

    # Build with watermark on every page
    doc.build(story, onFirstPage=_watermark, onLaterPages=_watermark)
    return buffer.getvalue()
