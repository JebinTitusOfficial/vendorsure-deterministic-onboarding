"""Generate the small synthetic PDFs used by VendorSure Phase 2 tests."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Mapping

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


DISCLAIMER = "SYNTHETIC DEMONSTRATION DOCUMENT — NOT VALID"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "pdfs"


def pdf_bytes(lines: list[str], *, blank: bool = False) -> bytes:
    """Return a small machine-readable PDF, or a textless PDF when blank."""

    output = BytesIO()
    document = canvas.Canvas(output, pagesize=letter)
    if not blank:
        y = 760
        document.setFont("Helvetica-Bold", 10)
        document.drawString(48, y, DISCLAIMER)
        y -= 28
        document.setFont("Helvetica", 10)
        for line in lines:
            document.drawString(48, y, line)
            y -= 18
    document.showPage()
    document.save()
    return output.getvalue()


def fixture_contents() -> Mapping[str, bytes]:
    """Return every generated fixture by its stable filename."""

    return {
        "apex_tax_certificate.pdf": pdf_bytes(
            [
                "LEGAL NAME: Apex Components Private Limited",
                "GSTIN: 27ABCDE1234F1Z5",
                "REGISTERED ADDRESS: 12 Synthetic Industrial Estate, Pune",
            ]
        ),
        "apex_bank_proof.pdf": pdf_bytes(
            [
                "ACCOUNT HOLDER: Apex Components Pvt Ltd",
                "ACCOUNT NUMBER: 100000000001",
                "IFSC: HDFC0001234",
                "BANK NAME: Synthetic HDFC Bank",
            ]
        ),
        "apex_compliance_declaration.pdf": pdf_bytes(
            [
                "SIGNATORY: Authorized Signatory",
                "DECLARATION DATE: 2026-01-15",
            ]
        ),
        "nova_tax_certificate.pdf": pdf_bytes(
            [
                "LEGAL NAME: Nova Industrial Services Private Limited",
                "GSTIN: 29NOVAQ1234G1Z6",
                "REGISTERED ADDRESS: 28 Synthetic Works, Bengaluru",
            ]
        ),
        "nova_bank_proof.pdf": pdf_bytes(
            [
                "ACCOUNT HOLDER: Nova Services",
                "ACCOUNT NUMBER: 100000000002",
                "IFSC: ICIC0005678",
                "BANK NAME: Synthetic ICICI Bank",
            ]
        ),
        "nova_compliance_declaration.pdf": pdf_bytes(
            [
                "SIGNATORY: Authorized Signatory",
                "DECLARATION DATE: 2026-01-15",
            ]
        ),
        "orion_tax_certificate.pdf": pdf_bytes(
            [
                "LEGAL NAME: Orion Trading Company",
                "GSTIN: 24ORION1234J1Z8",
                "REGISTERED ADDRESS: 7 Synthetic Market Road, Ahmedabad",
            ]
        ),
        "orion_bank_proof.pdf": pdf_bytes(
            [
                "ACCOUNT HOLDER: Orion Trading Company",
                "ACCOUNT NUMBER: 100000000003",
                "IFSC: AXIS0004321",
                "BANK NAME: Synthetic Axis Bank",
            ]
        ),
        "orion_compliance_declaration.pdf": pdf_bytes(
            [
                "SIGNATORY: Authorized Signatory",
                "DECLARATION DATE: 2026-01-15",
            ]
        ),
        "bluepeak_bank_proof.pdf": pdf_bytes(
            [
                "ACCOUNT HOLDER: BluePeak Logistics",
                "ACCOUNT NUMBER: 100000000004",
                "IFSC: YESB0002468",
                "BANK NAME: Synthetic Yes Bank",
            ]
        ),
        "bluepeak_compliance_declaration.pdf": pdf_bytes(
            [
                "SIGNATORY: Authorized Signatory",
                "DECLARATION DATE: 2026-01-15",
            ]
        ),
        "unreadable_blank.pdf": pdf_bytes([], blank=True),
    }


def generate_fixtures(output_dir: Path | str = DEFAULT_OUTPUT_DIR) -> tuple[Path, ...]:
    """Write all synthetic fixture PDFs and return their paths."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    paths = []
    for filename, content in fixture_contents().items():
        path = output_path / filename
        path.write_bytes(content)
        paths.append(path)
    return tuple(paths)


if __name__ == "__main__":
    generated = generate_fixtures()
    print(f"Generated {len(generated)} PDFs in {DEFAULT_OUTPUT_DIR}")