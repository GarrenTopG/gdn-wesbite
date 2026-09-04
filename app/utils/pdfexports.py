import io
from typing import List
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.entities import BeneficiaryNeed, Donation, Volunteer

# Helper function to create a base PDF document with a title and subtitle
def _create_base_document(buffer: io.BytesIO, title: str, subtitle: str) -> tuple[SimpleDocTemplate, list, dict]:
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    story = []
    styles = getSampleStyleSheet()

    header_style = ParagraphStyle(
        "DocHeader",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1e3a8a"),
        spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "DocSub",
        parent=styles["Normal"],
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#4b5563"),
        spaceAfter=15,
    )

    story.append(Paragraph(f"<b>Aurorah CAN</b> - {title}", header_style))
    story.append(Paragraph(subtitle, sub_style))
    story.append(Spacer(1, 10))

    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1f2937"),
    )

    header_cell_style = ParagraphStyle(
        "HeaderCell",
        parent=styles["Normal"],
        fontSize=9,
        leading=11,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    return doc, story, {"cell": cell_style, "header": header_cell_style}

# Function to generate a PDF report of volunteers with their details and statuses
def generate_volunteers_pdf(volunteers: List[Volunteer]) -> io.BytesIO:
    buffer = io.BytesIO()
    doc, story, styles = _create_base_document(
        buffer, "Volunteers Report", "List of registered community volunteers and assignment statuses."
    )

    table_data = [[
        Paragraph("ID", styles["header"]),
        Paragraph("Full Name", styles["header"]),
        Paragraph("Email", styles["header"]),
        Paragraph("Phone", styles["header"]),
        Paragraph("Skills / Role", styles["header"]),
        Paragraph("Status", styles["header"]),
    ]]

    for v in volunteers:
        table_data.append([
            Paragraph(str(v.id or "-"), styles["cell"]),
            Paragraph(v.full_name or "-", styles["cell"]),
            Paragraph(v.email or "-", styles["cell"]),
            Paragraph(v.phone or "-", styles["cell"]),
            Paragraph(v.skills or "-", styles["cell"]),
            Paragraph(str(v.status.value if hasattr(v.status, 'value') else v.status), styles["cell"]),
        ])

    table = Table(table_data, colWidths=[30, 150, 180, 100, 200, 80])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
    ]))

    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer

# Function to generate a PDF report of donations with their details
def generate_donations_pdf(donations: List[Donation]) -> io.BytesIO:
    buffer = io.BytesIO()
    doc, story, styles = _create_base_document(
        buffer, "Donations Ledger", "Record of monetary contributions and in-kind donation submissions."
    )

    table_data = [[
        Paragraph("ID", styles["header"]),
        Paragraph("Donor", styles["header"]),
        Paragraph("Type", styles["header"]),
        Paragraph("Amount / Item", styles["header"]),
        Paragraph("Need / Cause", styles["header"]),
        Paragraph("Verified", styles["header"]),
    ]]

    for d in donations:
        amount_desc = f"R{d.amount:.2f}" if d.amount else (d.item_description or "-")
        donor = "Anonymous" if d.is_anonymous else (d.donor_name or "N/A")
        table_data.append([
            Paragraph(str(d.id or "-"), styles["cell"]),
            Paragraph(donor, styles["cell"]),
            Paragraph(str(d.donation_type or "monetary"), styles["cell"]),
            Paragraph(amount_desc, styles["cell"]),
            Paragraph(str(d.need_id or "General Fund"), styles["cell"]),
            Paragraph("Yes" if d.is_verified else "No", styles["cell"]),
        ])

    table = Table(table_data, colWidths=[30, 140, 90, 240, 160, 60])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
    ]))

    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer

# Function to generate a PDF report of community needs
def generate_needs_pdf(needs: List[BeneficiaryNeed]) -> io.BytesIO:
    buffer = io.BytesIO()
    doc, story, styles = _create_base_document(
        buffer, "Community Needs Registry", "Active and historical beneficiary support requests."
    )

    table_data = [[
        Paragraph("ID", styles["header"]),
        Paragraph("Title", styles["header"]),
        Paragraph("Category", styles["header"]),
        Paragraph("Area", styles["header"]),
        Paragraph("Target (ZAR)", styles["header"]),
        Paragraph("Urgency", styles["header"]),
        Paragraph("Status", styles["header"]),
    ]]

    for n in needs:
        target_str = f"R{n.target_amount:.2f}" if n.target_amount else "R0.00"
        urgency_str = n.urgency.value if hasattr(n.urgency, 'value') else str(n.urgency)
        status_str = n.status.value if hasattr(n.status, 'value') else str(n.status)
        table_data.append([
            Paragraph(str(n.id or "-"), styles["cell"]),
            Paragraph(n.anonymised_title or "-", styles["cell"]),
            Paragraph(n.category or "-", styles["cell"]),
            Paragraph(n.area or "-", styles["cell"]),
            Paragraph(target_str, styles["cell"]),
            Paragraph(urgency_str, styles["cell"]),
            Paragraph(status_str, styles["cell"]),
        ])

    table = Table(table_data, colWidths=[30, 180, 110, 110, 100, 90, 90])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
    ]))

    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer

# Function to generate a PDF report of beneficiaries with their details and statuses
def generate_beneficiaries_pdf(needs: List[BeneficiaryNeed]) -> io.BytesIO:
    buffer = io.BytesIO()
    doc, story, styles = _create_base_document(
        buffer,
        "Beneficiary Assistance Requests",
        "Confidential POPIA-compliant beneficiary registry and fulfillment tracking.",
    )

    table_data = [[
        Paragraph("ID", styles["header"]),
        Paragraph("Beneficiary Contact (POPIA)", styles["header"]),
        Paragraph("Public Title & Area", styles["header"]),
        Paragraph("Category", styles["header"]),
        Paragraph("Urgency", styles["header"]),
        Paragraph("Funding (ZAR)", styles["header"]),
        Paragraph("Status", styles["header"]),
    ]]

    for n in needs:
        contact_info = f"<b>{n.contact_name or 'N/A'}</b><br/>{n.contact_phone or '-'}<br/>{n.full_address or '-'}"
        title_area = f"<b>{n.anonymised_title or '-'}</b><br/>{n.area or '-'}"
        funding_info = f"R{n.current_amount:.2f} / R{n.target_amount:.2f}"
        urgency_str = n.urgency.value if hasattr(n.urgency, "value") else str(n.urgency)
        status_str = n.status.value if hasattr(n.status, "value") else str(n.status)

        table_data.append([
            Paragraph(f"#{n.id or '-'}", styles["cell"]),
            Paragraph(contact_info, styles["cell"]),
            Paragraph(title_area, styles["cell"]),
            Paragraph(n.category or "-", styles["cell"]),
            Paragraph(urgency_str, styles["cell"]),
            Paragraph(funding_info, styles["cell"]),
            Paragraph(status_str, styles["cell"]),
        ])

    table = Table(table_data, colWidths=[30, 160, 160, 90, 70, 110, 80])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
    ]))

    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer