"""Deterministic extraction of labelled fields from machine-readable PDFs."""

from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass, field
from typing import BinaryIO, Mapping, Optional

import pdfplumber

from .models import DocumentEvidence
from .normalization import normalize_identifier, normalize_name, normalize_text
from .rules import BANK_DOCUMENT, COMPLIANCE_DECLARATION, TAX_CERTIFICATE


MAX_FILE_SIZE = 5 * 1024 * 1024

TAX_CERTIFICATE = "TAX_CERTIFICATE"
BANK_PROOF = "BANK_PROOF"
COMPLIANCE_DECLARATION = "COMPLIANCE_DECLARATION"

SUPPORTED_DOCUMENT_TYPES = frozenset(
    {TAX_CERTIFICATE, BANK_PROOF, COMPLIANCE_DECLARATION}
)

_FIELD_LABELS: Mapping[str, tuple[str, ...]] = {
    TAX_CERTIFICATE: ("LEGAL NAME", "GSTIN", "REGISTERED ADDRESS"),
    BANK_PROOF: ("ACCOUNT HOLDER", "ACCOUNT NUMBER", "IFSC", "BANK NAME"),
    COMPLIANCE_DECLARATION: ("SIGNATORY", "DECLARATION DATE"),
}


@dataclass(frozen=True)
class ExtractedField:
    """One extracted value and the evidence needed to explain it."""

    raw_value: str
    normalized_value: str
    source_document: str
    evidence_snippet: str

    @property
    def evidence(self) -> str:
        """Short alias for consumers that call the source text evidence."""

        return self.evidence_snippet


@dataclass(frozen=True)
class ExtractionResult:
    """Structured extraction output that never retains complete PDF text."""

    document_type: str
    source_filename: str
    original_filename: str
    sha256: Optional[str]
    accepted: bool
    readable: bool
    fields: Mapping[str, ExtractedField] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    @property
    def sanitized_filename(self) -> str:
        return self.source_filename

    @property
    def sha256_hash(self) -> Optional[str]:
        return self.sha256

    @property
    def failure_codes(self) -> tuple[str, ...]:
        return self.errors

    def field(self, name: str) -> Optional[ExtractedField]:
        return self.fields.get(name.upper())

    def to_document_evidence(self) -> DocumentEvidence:
        """Adapt this result to the Phase 1 rules-engine evidence model."""

        type_mapping = {
            TAX_CERTIFICATE: TAX_CERTIFICATE.lower(),
            BANK_PROOF: BANK_DOCUMENT,
            COMPLIANCE_DECLARATION: COMPLIANCE_DECLARATION.lower(),
        }
        field_mapping = {
            "LEGAL NAME": "legal_name",
            "GSTIN": "gstin",
            "REGISTERED ADDRESS": "registered_address",
            "ACCOUNT HOLDER": "account_holder",
            "ACCOUNT NUMBER": "account_number",
            "IFSC": "ifsc",
            "BANK NAME": "bank_name",
            "SIGNATORY": "signer",
            "DECLARATION DATE": "date",
        }
        extracted_fields = {
            field_mapping[name]: value.raw_value
            for name, value in self.fields.items()
            if name in field_mapping
        }
        return DocumentEvidence(
            document_type=type_mapping.get(self.document_type, self.document_type.lower()),
            source_document=self.source_filename,
            extracted_fields=extracted_fields,
            present=self.accepted,
            machine_readable=self.readable,
        )


def sanitize_filename(filename: str) -> str:
    """Return a safe basename without path traversal or unsafe characters."""

    candidate = str(filename or "document.pdf").replace("\\", "/")
    candidate = os.path.basename(candidate)
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate)
    candidate = re.sub(r"_+", "_", candidate).strip("._")
    return candidate or "document.pdf"


def _read_input(
    pdf_input: bytes | bytearray | BinaryIO | None,
) -> tuple[Optional[bytes], Optional[str]]:
    if pdf_input is None:
        return None, "FILE_MISSING"
    if isinstance(pdf_input, (bytes, bytearray)):
        return bytes(pdf_input), None
    if hasattr(pdf_input, "read"):
        try:
            position = pdf_input.tell() if hasattr(pdf_input, "tell") else None
            data = pdf_input.read()
            if position is not None and hasattr(pdf_input, "seek"):
                pdf_input.seek(position)
            if not isinstance(data, (bytes, bytearray)):
                return None, "FILE_READ_FAILED"
            return bytes(data), None
        except Exception:
            return None, "FILE_READ_FAILED"
    return None, "FILE_READ_FAILED"


def _normalized_value(field_name: str, raw_value: str) -> str:
    if field_name in {"LEGAL NAME", "ACCOUNT HOLDER", "BANK NAME", "SIGNATORY"}:
        return normalize_name(raw_value)
    if field_name in {"GSTIN", "ACCOUNT NUMBER", "IFSC"}:
        return normalize_identifier(raw_value)
    if field_name == "DECLARATION DATE":
        return raw_value.strip()
    return normalize_text(raw_value)


def _label_pattern(label: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(label)}\s*(?::|-)\s*(.*?)\s*$", re.IGNORECASE)


def _extract_fields(
    text: str,
    document_type: str,
    source_filename: str,
) -> tuple[dict[str, ExtractedField], tuple[str, ...]]:
    labels = _FIELD_LABELS[document_type]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    fields: dict[str, ExtractedField] = {}
    errors: list[str] = []

    for label in labels:
        pattern = _label_pattern(label)
        matching_line = next((line for line in lines if pattern.match(line)), None)
        if matching_line is None:
            errors.append(f"MISSING_LABEL:{label}")
            continue
        match = pattern.match(matching_line)
        raw_value = match.group(1).strip() if match else ""
        if not raw_value:
            errors.append(f"MISSING_VALUE:{label}")
            continue
        fields[label] = ExtractedField(
            raw_value=raw_value,
            normalized_value=_normalized_value(label, raw_value),
            source_document=source_filename,
            evidence_snippet=matching_line[:240],
        )
    return fields, tuple(errors)


def extract_document(
    pdf_input: bytes | bytearray | BinaryIO | None,
    document_type: str,
    filename: Optional[str] = None,
) -> ExtractionResult:
    """Extract labelled fields from a selected PDF document.

    The function accepts raw PDF bytes or a file-like object and converts all
    expected failure modes into a structured ``ExtractionResult``.
    """

    selected_type = str(document_type).upper()
    original_filename = filename
    if original_filename is None and pdf_input is not None:
        original_filename = getattr(pdf_input, "name", None)
    original_filename = str(original_filename or "document.pdf")
    source_filename = sanitize_filename(original_filename)

    data, read_error = _read_input(pdf_input)
    if read_error == "FILE_MISSING":
        return ExtractionResult(
            document_type=selected_type,
            source_filename=source_filename,
            original_filename=original_filename,
            sha256=None,
            accepted=False,
            readable=False,
            errors=(read_error,),
        )
    if read_error or data is None:
        return ExtractionResult(
            document_type=selected_type,
            source_filename=source_filename,
            original_filename=original_filename,
            sha256=None,
            accepted=False,
            readable=False,
            errors=(read_error or "FILE_READ_FAILED",),
        )

    digest = hashlib.sha256(data).hexdigest()
    if selected_type not in SUPPORTED_DOCUMENT_TYPES:
        return ExtractionResult(
            document_type=selected_type,
            source_filename=source_filename,
            original_filename=original_filename,
            sha256=digest,
            accepted=False,
            readable=False,
            errors=("UNSUPPORTED_DOCUMENT_TYPE",),
        )
    if len(data) > MAX_FILE_SIZE:
        return ExtractionResult(
            document_type=selected_type,
            source_filename=source_filename,
            original_filename=original_filename,
            sha256=digest,
            accepted=False,
            readable=False,
            errors=("FILE_TOO_LARGE",),
        )
    if not source_filename.lower().endswith(".pdf") or not data.startswith(b"%PDF-"):
        return ExtractionResult(
            document_type=selected_type,
            source_filename=source_filename,
            original_filename=original_filename,
            sha256=digest,
            accepted=False,
            readable=False,
            errors=("NOT_PDF",),
        )

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text_parts = [page.extract_text() or "" for page in pdf.pages]
    except Exception:
        return ExtractionResult(
            document_type=selected_type,
            source_filename=source_filename,
            original_filename=original_filename,
            sha256=digest,
            accepted=True,
            readable=False,
            errors=("DOC_READABLE:PDF could not be read",),
        )

    text = "\n".join(text_parts)
    if not text.strip():
        return ExtractionResult(
            document_type=selected_type,
            source_filename=source_filename,
            original_filename=original_filename,
            sha256=digest,
            accepted=True,
            readable=False,
            errors=("DOC_READABLE:PDF contains no extractable text",),
        )

    fields, extraction_errors = _extract_fields(text, selected_type, source_filename)
    return ExtractionResult(
        document_type=selected_type,
        source_filename=source_filename,
        original_filename=original_filename,
        sha256=digest,
        accepted=True,
        readable=True,
        fields=fields,
        errors=extraction_errors,
    )


def to_document_evidence(result: ExtractionResult) -> DocumentEvidence:
    """Convenience adapter for callers that prefer a standalone function."""

    return result.to_document_evidence()