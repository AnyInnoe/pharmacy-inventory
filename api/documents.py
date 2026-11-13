from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _safe_text(value):
    return escape(str(value or ""))


def _amount(value):
    return f"{value:,.2f}"


def _pdf_response(story):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Wellnest pharmacy document",
    )
    document.build(story)
    return buffer.getvalue()


def sale_receipt_pdf(sale):
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.alignment = TA_CENTER
    story = [
        Paragraph("Wellnest - Sale Receipt", title_style),
        Spacer(1, 8 * mm),
        Paragraph(f"<b>Branch:</b> {_safe_text(sale.branch.name)}", styles["Normal"]),
        Paragraph(f"<b>Receipt:</b> {_safe_text(sale.reference)}", styles["Normal"]),
        Paragraph(
            f"<b>Date:</b> {_safe_text(timezone.localtime(sale.recorded_at).strftime('%Y-%m-%d %H:%M'))}",
            styles["Normal"],
        ),
        Paragraph(
            f"<b>Served by:</b> {_safe_text(sale.actor.get_full_name() or sale.actor.get_username() if sale.actor else 'Staff')}",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
    ]

    rows = [["Product", "Qty", "Unit price", "Amount"]]
    for line in sale.lines.select_related("batch__product").all():
        rows.append([
            Paragraph(_safe_text(line.batch.product.name), styles["BodyText"]),
            str(line.quantity),
            _amount(line.selling_price),
            _amount(line.selling_price * line.quantity),
        ])
    table = Table(rows, colWidths=[86 * mm, 18 * mm, 33 * mm, 33 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeF8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#292746")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d9e2")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([
        table,
        Spacer(1, 5 * mm),
        Paragraph(f"<b>Total:</b> {_amount(sale.sale_amount)}", styles["Normal"]),
        Paragraph(f"<b>Paid:</b> {_amount(sale.amount_received)}", styles["Normal"]),
        Paragraph(f"<b>Balance:</b> {_amount(sale.balance_due)}", styles["Normal"]),
        Paragraph(f"<b>Payment method:</b> {_safe_text(sale.payment_method)}", styles["Normal"]),
        Spacer(1, 8 * mm),
        Paragraph("Thank you for your purchase.", styles["Normal"]),
    ])
    return _pdf_response(story)


def invoice_reconciliation_pdf(invoice):
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.alignment = TA_CENTER
    story = [
        Paragraph("Wellnest - Supplier Invoice Reconciliation", title_style),
        Spacer(1, 5 * mm),
        Paragraph(
            "Internal reconciliation copy - not the supplier's original invoice or a tax invoice.",
            styles["Italic"],
        ),
        Spacer(1, 5 * mm),
        Paragraph(f"<b>Branch:</b> {_safe_text(invoice.branch.name)}", styles["Normal"]),
        Paragraph(f"<b>System reference:</b> INV-{invoice.pk:06d}", styles["Normal"]),
        Paragraph(f"<b>Supplier:</b> {_safe_text(invoice.supplier)}", styles["Normal"]),
        Paragraph(f"<b>Supplier invoice:</b> {_safe_text(invoice.invoice_number)}", styles["Normal"]),
        Paragraph(f"<b>Due date:</b> {_safe_text(invoice.due_date.isoformat())}", styles["Normal"]),
        Paragraph(
            f"<b>Reconciliation:</b> {_safe_text(invoice.get_reconciliation_status_display())}",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
    ]
    if invoice.purchase_order_id:
        rows = [["Product", "Ordered", "Received", "Unit cost", "Expected"]]
        for line in invoice.purchase_order.lines.select_related("product").all():
            rows.append([
                Paragraph(
                    f"{_safe_text(line.product.name)}<br/><font size='8'>{_safe_text(line.product.sku)}</font>",
                    styles["BodyText"],
                ),
                str(line.quantity_ordered),
                str(line.quantity_received),
                _amount(line.unit_cost),
                _amount(line.unit_cost * line.quantity_received),
            ])
        table = Table(
            rows,
            colWidths=[70 * mm, 22 * mm, 22 * mm, 28 * mm, 28 * mm],
            repeatRows=1,
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeF8")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#292746")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d9e2")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.extend([table, Spacer(1, 5 * mm)])
    story.extend([
        Paragraph(f"<b>Invoice total:</b> {_amount(invoice.invoice_amount)}", styles["Normal"]),
        Paragraph(f"<b>Amount paid:</b> {_amount(invoice.amount_paid)}", styles["Normal"]),
        Paragraph(
            f"<b>Expected from received stock:</b> {_amount(invoice.reconciled_expected_amount)}"
            if invoice.reconciled_expected_amount is not None
            else "<b>Expected from received stock:</b> Not reconciled",
            styles["Normal"],
        ),
        Paragraph(
            f"<b>Variance:</b> {_amount(invoice.reconciliation_variance)}"
            if invoice.reconciliation_variance is not None
            else "<b>Variance:</b> Not reconciled",
            styles["Normal"],
        ),
    ])
    return _pdf_response(story)
