"""
pdf_generator.py – ReportLab PDF generation for Eligald.
Includes: professional invoice generator (with watermark, logo, tax toggle)
and a downloadable product catalogue generator.
"""
import io, os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, Image
)

# ── Brand colours ─────────────────────────────────────────────────────────────
GREEN_DARK  = colors.HexColor("#1B5E20")
GREEN_MID   = colors.HexColor("#2E7D32")
GREEN_LIGHT = colors.HexColor("#C8E6C9")
GREEN_PALE  = colors.HexColor("#F1F8E9")
CHARCOAL    = colors.HexColor("#2D2D2D")
GREY        = colors.HexColor("#757575")
GREY_LIGHT  = colors.HexColor("#EEEEEE")
WHITE       = colors.white

LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "images", "logo.png")
TAX_RATE  = 0.16


def _watermark(canvas, doc):
    """Draw semi-transparent logo watermark on every page. Never crashes."""
    try:
        if not os.path.exists(LOGO_PATH):
            return
        canvas.saveState()
        canvas.setFillAlpha(0.06)
        w, h = A4
        img_w, img_h = 160*mm, 160*mm
        x = (w - img_w) / 2
        y = (h - img_h) / 2
        canvas.drawImage(LOGO_PATH, x, y, width=img_w, height=img_h,
                         preserveAspectRatio=True, mask='auto')
        canvas.restoreState()
    except Exception:
        try: canvas.restoreState()
        except Exception: pass


def generate_invoice_pdf(order, items, settings, include_tax=None):
    buffer = io.BytesIO()
    if include_tax is None:
        include_tax = bool(order.get("include_tax", 1))

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=16*mm, leftMargin=16*mm,
        topMargin=14*mm, bottomMargin=20*mm,
    )
    co_name  = settings.get("company_name", "Eligald Industrial Chemicals Limited")
    co_addr  = settings.get("address", "Imara Daima, Along Enterprise Road, Opp SMK Business Centre, Nairobi, Kenya")
    co_phone = settings.get("phone", "+254 719 655 694")
    co_email = settings.get("email", "eligald.chemicals26@gmail.com")
    co_wa    = settings.get("whatsapp_number", "254719655694")

    story = []

    logo_cell = Paragraph("<font color='#1B5E20'><b>Eligald</b></font>",
                          ParagraphStyle("li", fontSize=14, textColor=GREEN_DARK, fontName="Helvetica-Bold"))
    if os.path.exists(LOGO_PATH):
        try:
            logo_img = Image(LOGO_PATH, width=38*mm, height=38*mm)
            logo_img.hAlign = "LEFT"
            logo_cell = logo_img
        except Exception:
            pass

    co_style = ParagraphStyle("co", fontSize=7.5, leading=11.5, textColor=CHARCOAL)
    co_bold  = ParagraphStyle("cob", fontSize=10, leading=14, textColor=GREEN_DARK, fontName="Helvetica-Bold")
    inv_style = ParagraphStyle("inv", fontSize=22, textColor=GREEN_DARK, fontName="Helvetica-Bold",
                               alignment=TA_RIGHT, spaceAfter=6, leading=26)
    inv_meta  = ParagraphStyle("im", fontSize=8, leading=13, textColor=GREY, alignment=TA_RIGHT)

    status_colour = {"draft":"#9E9E9E","sent":"#1565C0","paid":"#1B5E20","cancelled":"#B71C1C"}.get(order.get("status","draft"), "#9E9E9E")

    header_data = [[
        logo_cell,
        [Paragraph(co_name, co_bold), Paragraph(co_addr, co_style),
         Paragraph(f"Tel: {co_phone}", co_style), Paragraph(f"Email: {co_email}", co_style),
         Paragraph(f"WhatsApp: +{co_wa}", co_style)],
        [
            Paragraph("INVOICE", inv_style),
            Paragraph(
                f"<b>No:</b> {order['invoice_number']}<br/>"
                f"<b>Date:</b> {order['issued_date']}<br/>"
                f"<b>Due:</b> {order['due_date']}<br/>"
                f"<font color='{status_colour}'><b>{order.get('status','').upper()}</b></font>",
                inv_meta
            ),
        ],
    ]]
    header_tbl = Table(header_data, colWidths=[40*mm, 74*mm, 64*mm])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"), ("BACKGROUND", (0,0), (-1,-1), GREEN_PALE),
        ("TOPPADDING", (0,0), (-1,-1), 10), ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING", (0,0), (0,-1), 6),
        ("RIGHTPADDING", (-1,0), (-1,-1), 8), ("LINEBELOW", (0,0), (-1,-1), 2.5, GREEN_MID),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 5*mm))

    bt_label = ParagraphStyle("btl", fontSize=7, textColor=WHITE, fontName="Helvetica-Bold", leftPadding=6)
    bt_body  = ParagraphStyle("btb", fontSize=8.5, leading=13, textColor=CHARCOAL, leftPadding=6)

    bill_data = [[
        Paragraph("BILL TO", bt_label), Paragraph("INVOICE DETAILS", bt_label)
    ],[
        Paragraph(f"<b>{order['customer_name']}</b><br/>{order.get('customer_email','')}<br/>"
                  f"{order.get('customer_phone','')}<br/>{order.get('billing_address','')}", bt_body),
        Paragraph(f"<b>Invoice #:</b> {order['invoice_number']}<br/><b>Issued:</b> {order['issued_date']}<br/>"
                  f"<b>Due Date:</b> {order['due_date']}<br/>"
                  f"<b>Tax:</b> {'16% VAT Included' if include_tax else 'No Tax / Tax Exempt'}", bt_body),
    ]]
    bill_tbl = Table(bill_data, colWidths=[89*mm, 89*mm])
    bill_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), GREEN_DARK), ("TEXTCOLOR", (0,0), (-1,0), WHITE),
        ("BACKGROUND", (0,1), (-1,-1), WHITE), ("BOX", (0,0), (-1,-1), 0.5, GREEN_LIGHT),
        ("LINEAFTER", (0,0), (0,-1), 0.5, GREEN_LIGHT), ("ROWPADDING", (0,0), (-1,-1), 5),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(bill_tbl)
    story.append(Spacer(1, 6*mm))

    rows = [["#","Description","Qty","Unit","Unit Price (KES)","Total (KES)"]]
    subtotal = 0.0
    for i, it in enumerate(items, 1):
        rows.append([str(i), it.get("description",""), f"{float(it.get('quantity',1)):.2f}",
                    it.get("unit",""), f"{float(it.get('unit_price',0)):,.2f}",
                    f"{float(it.get('total_price',0)):,.2f}"])
        subtotal += float(it.get("total_price", 0))

    tax_amt     = subtotal * TAX_RATE if include_tax else 0.0
    total       = subtotal + tax_amt
    amount_paid = float(order.get("amount_paid") or 0)
    amount_due  = max(0.0, total - amount_paid)

    rows.append(["","","","","Subtotal", f"{subtotal:,.2f}"])
    if include_tax:
        rows.append(["","","","",f"VAT ({int(TAX_RATE*100)}%)", f"{tax_amt:,.2f}"])
    rows.append(["","","","","TOTAL", f"KES {total:,.2f}"])
    if amount_paid > 0:
        rows.append(["","","","","Amount Paid", f"KES {amount_paid:,.2f}"])
        rows.append(["","","","","Amount Due", f"KES {amount_due:,.2f}"])

    n = len(rows)
    col_w = [8*mm, 62*mm, 14*mm, 14*mm, 32*mm, 28*mm]
    items_tbl = Table(rows, colWidths=col_w, repeatRows=1)

    # Row indices for styling (from the bottom up)
    total_row_idx = n - 3 if amount_paid > 0 else n - 1  # the "TOTAL" row
    subtotal_start = total_row_idx - (2 if include_tax else 1)  # first summary row (Subtotal)

    _style_cmds = [
        ("BACKGROUND", (0,0), (-1,0), GREEN_DARK), ("TEXTCOLOR", (0,0), (-1,0), WHITE),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,0), 8),
        ("ROWBACKGROUNDS", (0,1), (-1, subtotal_start-1), [WHITE, GREEN_PALE]),
        ("FONTSIZE", (0,1), (-1,-1), 8), ("TEXTCOLOR", (0,1), (-1,-1), CHARCOAL),
        ("BACKGROUND", (4, subtotal_start), (-1, total_row_idx-1), GREEN_PALE),
        ("FONTNAME", (4, subtotal_start), (-1, total_row_idx-1), "Helvetica-Bold"),
        ("BACKGROUND", (4, total_row_idx), (-1, total_row_idx), GREEN_DARK),
        ("TEXTCOLOR", (4, total_row_idx), (-1, total_row_idx), WHITE),
        ("FONTNAME", (4, total_row_idx), (-1, total_row_idx), "Helvetica-Bold"),
        ("FONTSIZE", (4, total_row_idx), (-1, total_row_idx), 9),
        ("GRID", (0,0), (-1, subtotal_start-1), 0.4, GREEN_LIGHT),
        ("LINEABOVE", (0, subtotal_start), (-1, -1), 0.8, GREEN_MID),
        ("ALIGN", (2,0), (-1,-1), "RIGHT"), ("ALIGN", (0,0), (0,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("ROWPADDING", (0,0), (-1,-1), 5),
    ]
    if amount_paid > 0:
        # Amount Paid row (green text) and Amount Due row (bold, colour depends on balance)
        due_colour = "#1B5E20" if amount_due <= 0 else "#C62828"
        _style_cmds += [
            ("TEXTCOLOR", (4, total_row_idx+1), (-1, total_row_idx+1), GREEN_MID),
            ("FONTNAME", (4, total_row_idx+1), (-1, total_row_idx+1), "Helvetica-Bold"),
            ("BACKGROUND", (4, total_row_idx+2), (-1, total_row_idx+2),
                colors.HexColor("#E8F5E9") if amount_due <= 0 else colors.HexColor("#FFEBEE")),
            ("TEXTCOLOR", (4, total_row_idx+2), (-1, total_row_idx+2), colors.HexColor(due_colour)),
            ("FONTNAME", (4, total_row_idx+2), (-1, total_row_idx+2), "Helvetica-Bold"),
            ("FONTSIZE", (4, total_row_idx+2), (-1, total_row_idx+2), 9),
        ]

    items_tbl.setStyle(TableStyle(_style_cmds))
    story.append(items_tbl)
    story.append(Spacer(1, 4*mm))

    if order.get("payment_method") or amount_paid > 0:
        _pm = order.get("payment_method") or "Not specified"
        _pn = order.get("payment_notes") or ""
        _pay_summary = f"<b>Payment Method:</b> {_pm}"
        if _pn:
            _pay_summary += f" &nbsp;|&nbsp; <b>Note:</b> {_pn}"
        story.append(Paragraph(_pay_summary,
                     ParagraphStyle("paymeth", fontSize=8, textColor=CHARCOAL, leading=12)))
        story.append(Spacer(1, 4*mm))

    if order.get("notes"):
        story.append(Paragraph(f"<b>Notes:</b> {order['notes']}",
                     ParagraphStyle("notes", fontSize=8, textColor=GREY, leading=12)))
        story.append(Spacer(1, 4*mm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=GREEN_LIGHT))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        f"<b><font color='#2E7D32'>Payment Instructions</font></b><br/>"
        f"M-Pesa Paybill / Bank transfer details provided on request.<br/>"
        f"Queries: {co_email} | WhatsApp: +{co_wa}",
        ParagraphStyle("pay", fontSize=8, leading=12, textColor=CHARCOAL)))
    story.append(Spacer(1, 6*mm))

    story.append(HRFlowable(width="100%", thickness=1.5, color=GREEN_MID))
    story.append(Spacer(1, 2*mm))
    footer_style = ParagraphStyle("ft", fontSize=7.5, textColor=CHARCOAL, alignment=TA_CENTER, leading=11)
    footer_data = [[
        Paragraph(f"<b>{co_name}</b>", footer_style), Paragraph(f"{co_addr}", footer_style),
        Paragraph(f"{co_phone}", footer_style), Paragraph(f"{co_email}", footer_style),
        Paragraph(f"+{co_wa}", footer_style),
    ]]
    footer_tbl = Table(footer_data, colWidths=[48*mm, 42*mm, 34*mm, 38*mm, 26*mm])
    footer_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), GREEN_PALE), ("ROWPADDING", (0,0), (-1,-1), 5),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("FONTSIZE", (0,0), (-1,-1), 7),
        ("LINEAFTER", (0,0), (-2,-1), 0.3, GREEN_LIGHT),
    ]))
    story.append(footer_tbl)

    doc.build(story, onFirstPage=_watermark, onLaterPages=_watermark)
    return buffer.getvalue()


def generate_catalogue_pdf(products, settings, categories=None):
    """Downloadable product catalogue PDF grouped by category."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=18*mm, leftMargin=18*mm,
        topMargin=16*mm, bottomMargin=18*mm,
    )
    co_name  = settings.get("company_name", "Eligald Industrial Chemicals Limited")
    co_addr  = settings.get("address", "Imara Daima, Along Enterprise Road, Opp SMK Business Centre, Nairobi, Kenya")
    co_phone = settings.get("phone", "")
    co_email = settings.get("email", "")

    title_style = ParagraphStyle("cat_title", fontSize=22, textColor=GREEN_DARK,
                                 fontName="Helvetica-Bold", spaceAfter=4)
    sub_style = ParagraphStyle("cat_sub", fontSize=10, textColor=GREY, spaceAfter=16)
    cat_header_style = ParagraphStyle("cat_head", fontSize=13, textColor=WHITE, fontName="Helvetica-Bold")
    prod_desc_style = ParagraphStyle("prod_desc", fontSize=8.5, textColor=GREY, leading=12)
    prod_price_style = ParagraphStyle("prod_price", fontSize=9.5, fontName="Helvetica-Bold",
                                      textColor=GREEN_MID, alignment=TA_RIGHT)

    story = []
    if os.path.exists(LOGO_PATH):
        try:
            story.append(Image(LOGO_PATH, width=34*mm, height=34*mm))
            story.append(Spacer(1, 4*mm))
        except Exception: pass

    story.append(Paragraph(co_name, title_style))
    story.append(Paragraph("Full Product Catalogue", sub_style))
    story.append(Paragraph(f"{co_addr} | {co_phone} | {co_email}",
                 ParagraphStyle("contact", fontSize=8.5, textColor=GREY, spaceAfter=14)))
    story.append(HRFlowable(width="100%", thickness=1.2, color=GREEN_MID))
    story.append(Spacer(1, 6*mm))

    grouped = {}
    for p in products:
        grouped.setdefault(p.get("category", "Other"), []).append(p)
    cat_order = categories if categories else sorted(grouped.keys())

    for cat in cat_order:
        items = grouped.get(cat)
        if not items: continue
        cat_bar = Table([[Paragraph(cat, cat_header_style)]], colWidths=[174*mm])
        cat_bar.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),GREEN_DARK), ("ROWPADDING",(0,0),(-1,-1),7),
            ("LEFTPADDING",(0,0),(-1,-1),10),
        ]))
        story.append(cat_bar)
        story.append(Spacer(1, 3*mm))

        for p in items:
            price = p.get("price_per_unit")
            price_txt = f"KES {price:,.2f}" if price else "On enquiry"
            row = Table([[
                Paragraph(f"{p.get('name','')}<br/><font size=8 color='#888'>{(p.get('description') or '')[:140]}</font>", prod_desc_style),
                Paragraph(price_txt, prod_price_style),
            ]], colWidths=[134*mm, 40*mm])
            row.setStyle(TableStyle([
                ("VALIGN",(0,0),(-1,-1),"TOP"), ("BOTTOMPADDING",(0,0),(-1,-1),8),
                ("LINEBELOW",(0,0),(-1,-1),0.4,GREY_LIGHT),
            ]))
            story.append(row)
        story.append(Spacer(1, 5*mm))

    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=0.6, color=GREEN_LIGHT))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph("Prices subject to change. Contact us via WhatsApp or email for a formal quotation.",
                 ParagraphStyle("disc", fontSize=7.5, textColor=GREY, alignment=TA_CENTER)))

    doc.build(story, onFirstPage=_watermark, onLaterPages=_watermark)
    return buffer.getvalue()
