from hashlib import sha256
from io import BytesIO

from fixtures.generate_fixtures import pdf_bytes
from vendorsure.extraction import (
    BANK_PROOF,
    MAX_FILE_SIZE,
    TAX_CERTIFICATE,
    extract_document,
    sanitize_filename,
)


def test_tax_certificate_extraction_preserves_raw_normalized_and_evidence():
    data = pdf_bytes(
        [
            "LEGAL NAME: Apex Components Private Limited",
            "GSTIN: 27ABCDE1234F1Z5",
            "REGISTERED ADDRESS: 12 Synthetic Industrial Estate",
        ]
    )
    result = extract_document(data, TAX_CERTIFICATE, "../../Apex Tax!.pdf")

    assert result.accepted
    assert result.readable
    assert result.sha256 == sha256(data).hexdigest()
    assert result.source_filename == "Apex_Tax_.pdf"
    assert result.field("LEGAL NAME").raw_value == "Apex Components Private Limited"
    assert result.field("LEGAL NAME").normalized_value == "apex components"
    assert result.field("LEGAL NAME").evidence == (
        "LEGAL NAME: Apex Components Private Limited"
    )
    assert result.field("GSTIN").normalized_value == "27ABCDE1234F1Z5"


def test_bank_proof_extraction():
    result = extract_document(
        BytesIO(
            pdf_bytes(
                [
                    "ACCOUNT HOLDER: Apex Components Pvt Ltd",
                    "ACCOUNT NUMBER: 100000000001",
                    "IFSC: HDFC0001234",
                    "BANK NAME: Synthetic HDFC Bank",
                ]
            )
        ),
        BANK_PROOF,
        "bank-proof.pdf",
    )

    assert result.readable
    assert result.field("ACCOUNT HOLDER").raw_value == "Apex Components Pvt Ltd"
    assert result.field("ACCOUNT HOLDER").normalized_value == "apex components"
    assert result.field("ACCOUNT NUMBER").normalized_value == "100000000001"
    assert result.field("IFSC").normalized_value == "HDFC0001234"


def test_compliance_declaration_extraction():
    from vendorsure.extraction import COMPLIANCE_DECLARATION

    result = extract_document(
        pdf_bytes(
            [
                "SIGNATORY: Authorized Signatory",
                "DECLARATION DATE: 2026-01-15",
            ]
        ),
        COMPLIANCE_DECLARATION,
        "compliance.pdf",
    )

    assert result.field("SIGNATORY").raw_value == "Authorized Signatory"
    assert result.field("DECLARATION DATE").normalized_value == "2026-01-15"
    assert not result.errors


def test_blank_pdf_is_structured_as_unreadable():
    result = extract_document(pdf_bytes([], blank=True), TAX_CERTIFICATE, "blank.pdf")

    assert result.accepted
    assert not result.readable
    assert result.fields == {}
    assert any(error.startswith("DOC_READABLE:") for error in result.errors)


def test_corrupt_pdf_is_structured_as_unreadable():
    result = extract_document(b"%PDF-corrupt", TAX_CERTIFICATE, "corrupt.pdf")

    assert result.accepted
    assert not result.readable
    assert any(error.startswith("DOC_READABLE:") for error in result.errors)


def test_non_pdf_is_rejected():
    result = extract_document(b"not a PDF", TAX_CERTIFICATE, "document.txt")

    assert not result.accepted
    assert result.errors == ("NOT_PDF",)


def test_oversized_file_is_rejected_before_pdf_parsing():
    data = b"%PDF-" + b"x" * MAX_FILE_SIZE
    result = extract_document(data, TAX_CERTIFICATE, "large.pdf")

    assert not result.accepted
    assert result.errors == ("FILE_TOO_LARGE",)
    assert result.sha256 == sha256(data).hexdigest()


def test_missing_expected_labels_are_reported_without_crashing():
    result = extract_document(
        pdf_bytes(["LEGAL NAME: Partial Vendor"]),
        TAX_CERTIFICATE,
        "partial.pdf",
    )

    assert result.accepted
    assert result.readable
    assert result.field("LEGAL NAME") is not None
    assert "MISSING_LABEL:GSTIN" in result.errors
    assert "MISSING_LABEL:REGISTERED ADDRESS" in result.errors


def test_missing_file_and_filename_sanitization():
    result = extract_document(None, TAX_CERTIFICATE, "../../../missing.pdf")

    assert not result.accepted
    assert result.errors == ("FILE_MISSING",)
    assert result.source_filename == "missing.pdf"
    assert sanitize_filename(r"..\unsafe folder\vendor report!.pdf") == "vendor_report_.pdf"


def test_extraction_result_adapts_to_phase_one_document_evidence():
    result = extract_document(
        pdf_bytes(
            [
                "LEGAL NAME: Apex Components Private Limited",
                "GSTIN: 27ABCDE1234F1Z5",
                "REGISTERED ADDRESS: Synthetic Address",
            ]
        ),
        TAX_CERTIFICATE,
        "tax.pdf",
    )
    evidence = result.to_document_evidence()

    assert evidence.document_type == "tax_certificate"
    assert evidence.source_document == "tax.pdf"
    assert evidence.present
    assert evidence.machine_readable
    assert evidence.extracted_fields["legal_name"] == "Apex Components Private Limited"