"""Explicit, deterministic validation rules for VendorSure."""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable, Mapping, Optional, Sequence

from .models import DocumentEvidence, VendorSubmission, ValidationResult
from .normalization import (
    names_match,
    normalize_email,
    normalize_identifier,
    normalize_name,
)


RULE_VERSION = "1.0"

TAX_CERTIFICATE = "tax_certificate"
BANK_DOCUMENT = "bank_document"
COMPLIANCE_DECLARATION = "compliance_declaration"

_GSTIN_PATTERN = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$",
    re.IGNORECASE,
)
_IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _result(
    *,
    rule_code: str,
    category: str,
    passed: bool,
    message: str,
    submitted_value: str = "",
    reference_value: str = "",
    source_document: str = "",
    next_action: str = "",
    severity: Optional[str] = None,
) -> ValidationResult:
    return ValidationResult(
        rule_code=rule_code,
        category=category,
        passed=passed,
        severity=severity if not passed else None,
        message=message,
        submitted_value=submitted_value,
        reference_value=reference_value,
        source_document=source_document,
        next_action=next_action,
        rule_version=RULE_VERSION,
    )


def _document(submission: VendorSubmission, document_type: str) -> Optional[DocumentEvidence]:
    return submission.document(document_type)


def required_field_rules(submission: VendorSubmission) -> list[ValidationResult]:
    """Check the presence of fields needed by the remaining rules."""

    required = (
        ("legal_name", submission.legal_name),
        ("gstin", submission.gstin),
        ("email", submission.email),
        ("ifsc", submission.ifsc),
        ("bank_account", submission.bank_account),
        ("bank_account_holder", submission.bank_account_holder),
    )
    results: list[ValidationResult] = []
    for field_name, value in required:
        present = bool(str(value).strip())
        results.append(
            _result(
                rule_code=f"REQUIRED_{field_name.upper()}",
                category="FORMAT",
                passed=present,
                message=(
                    f"{field_name} was provided."
                    if present
                    else f"{field_name} is required."
                ),
                submitted_value=str(value),
                next_action="" if present else f"Provide {field_name}.",
                severity=None if present else "PENDING",
            )
        )
    return results


def document_required_rule(
    submission: VendorSubmission,
    document_type: str = TAX_CERTIFICATE,
) -> ValidationResult:
    """Require the tax certificate needed for tax consistency checks."""

    document = _document(submission, document_type)
    passed = document is not None
    return _result(
        rule_code="DOC_REQUIRED",
        category="DOCUMENT",
        passed=passed,
        message=(
            f"{document_type} is present."
            if passed
            else f"Required document is missing: {document_type}."
        ),
        submitted_value=document_type if passed else "",
        reference_value=document_type,
        source_document=document.source_document if document else "",
        next_action="" if passed else f"Upload the {document_type}.",
        severity=None if passed else "PENDING",
    )


def document_readable_rules(submission: VendorSubmission) -> list[ValidationResult]:
    """Return PENDING failures for present documents without readable text."""

    results: list[ValidationResult] = []
    for document in submission.documents:
        if not document.present or document.machine_readable:
            continue
        results.append(
            _result(
                rule_code="DOC_READABLE",
                category="DOCUMENT",
                passed=False,
                message=f"Document could not be read: {document.source_document}.",
                submitted_value=document.source_document,
                reference_value="Machine-readable PDF text",
                source_document=document.source_document,
                next_action="Upload a machine-readable PDF or route the document for manual review.",
                severity="PENDING",
            )
        )
    return results


def gstin_structure_rule(submission: VendorSubmission) -> ValidationResult:
    value = normalize_identifier(submission.gstin)
    passed = bool(_GSTIN_PATTERN.fullmatch(value))
    return _result(
        rule_code="GSTIN_FORMAT",
        category="FORMAT",
        passed=passed,
        message=(
            "GSTIN has the expected 15-character structure."
            if passed
            else "GSTIN does not have the expected structure."
        ),
        submitted_value=submission.gstin,
        reference_value="15-character GSTIN structure",
        next_action="" if passed else "Correct the GSTIN format.",
        severity=None if passed else "PENDING",
    )


def ifsc_structure_rule(submission: VendorSubmission) -> ValidationResult:
    value = normalize_identifier(submission.ifsc)
    passed = bool(_IFSC_PATTERN.fullmatch(value))
    return _result(
        rule_code="IFSC_FORMAT",
        category="FORMAT",
        passed=passed,
        message=(
            "IFSC has the expected 11-character structure."
            if passed
            else "IFSC does not have the expected structure."
        ),
        submitted_value=submission.ifsc,
        reference_value="11-character IFSC structure",
        next_action="" if passed else "Correct the IFSC format.",
        severity=None if passed else "PENDING",
    )


def email_structure_rule(submission: VendorSubmission) -> ValidationResult:
    value = normalize_email(submission.email)
    passed = bool(_EMAIL_PATTERN.fullmatch(value))
    return _result(
        rule_code="EMAIL_FORMAT",
        category="FORMAT",
        passed=passed,
        message=(
            "Email has a valid basic structure."
            if passed
            else "Email does not have a valid basic structure."
        ),
        submitted_value=submission.email,
        reference_value="local-part@domain",
        next_action="" if passed else "Correct the email address.",
        severity=None if passed else "PENDING",
    )


def _tax_document_field(
    submission: VendorSubmission,
    field_name: str,
) -> tuple[Optional[DocumentEvidence], Optional[str]]:
    document = _document(submission, TAX_CERTIFICATE)
    return document, document.field(field_name) if document else None


def legal_name_match_rule(submission: VendorSubmission) -> ValidationResult:
    document, reference = _tax_document_field(submission, "legal_name")
    if document is None:
        return _result(
            rule_code="LEGAL_NAME_MATCH",
            category="CONSISTENCY",
            passed=True,
            message="Skipped because the tax certificate is missing.",
            submitted_value=submission.legal_name,
            reference_value="",
            next_action="",
        )
    if not reference:
        return _result(
            rule_code="LEGAL_NAME_MATCH",
            category="CONSISTENCY",
            passed=False,
            message="Tax certificate does not contain a legal name.",
            submitted_value=submission.legal_name,
            reference_value="",
            source_document=document.source_document,
            next_action="Provide a tax certificate with the legal name.",
            severity="PENDING",
        )

    passed = names_match(submission.legal_name, reference)
    return _result(
        rule_code="LEGAL_NAME_MATCH",
        category="CONSISTENCY",
        passed=passed,
        message=(
            "Submitted legal name matches the tax certificate."
            if passed
            else "Submitted legal name does not match the tax certificate."
        ),
        submitted_value=submission.legal_name,
        reference_value=reference,
        source_document=document.source_document,
        next_action="" if passed else "Review the legal name and tax certificate.",
        severity=None if passed else "PENDING",
    )


def gstin_match_rule(submission: VendorSubmission) -> ValidationResult:
    document, reference = _tax_document_field(submission, "gstin")
    if document is None:
        return _result(
            rule_code="GSTIN_MATCH",
            category="CONSISTENCY",
            passed=True,
            message="Skipped because the tax certificate is missing.",
            submitted_value=submission.gstin,
            reference_value="",
            next_action="",
        )
    if not reference:
        return _result(
            rule_code="GSTIN_MATCH",
            category="CONSISTENCY",
            passed=False,
            message="Tax certificate does not contain a GSTIN.",
            submitted_value=submission.gstin,
            reference_value="",
            source_document=document.source_document,
            next_action="Provide a tax certificate with the GSTIN.",
            severity="PENDING",
        )

    passed = normalize_identifier(submission.gstin) == normalize_identifier(reference)
    return _result(
        rule_code="GSTIN_MATCH",
        category="CONSISTENCY",
        passed=passed,
        message=(
            "Submitted GSTIN matches the tax certificate."
            if passed
            else "Submitted GSTIN does not match the tax certificate."
        ),
        submitted_value=submission.gstin,
        reference_value=reference,
        source_document=document.source_document,
        next_action="" if passed else "Review the GSTIN and tax certificate.",
        severity=None if passed else "PENDING",
    )


def bank_name_match_rule(submission: VendorSubmission) -> ValidationResult:
    accepted_names = [submission.legal_name]
    if submission.declared_trade_name:
        accepted_names.append(submission.declared_trade_name)
    passed = any(names_match(submission.bank_account_holder, name) for name in accepted_names)
    reference = " or ".join(name for name in accepted_names if name)
    bank_document = _document(submission, BANK_DOCUMENT)
    source = bank_document.source_document if bank_document else ""
    return _result(
        rule_code="BANK_NAME_MATCH",
        category="CONSISTENCY",
        passed=passed,
        message=(
            "Bank-account holder matches the legal name or declared trade name."
            if passed
            else "Bank-account holder does not match the legal name or declared trade name."
        ),
        submitted_value=submission.bank_account_holder,
        reference_value=reference,
        source_document=source,
        next_action="" if passed else "Confirm the bank holder name or declare the trade name.",
        severity=None if passed else "PENDING",
    )


def compliance_signer_rule(submission: VendorSubmission) -> ValidationResult:
    document = _document(submission, COMPLIANCE_DECLARATION)
    document_signer = document.field("signer") if document else None
    submitted = submission.compliance_signer or ""
    if not submitted or not document_signer:
        return _result(
            rule_code="COMPLIANCE_SIGNER",
            category="CONSISTENCY",
            passed=False,
            message="Compliance declaration signer is missing.",
            submitted_value=submitted,
            reference_value=document_signer or "",
            source_document=document.source_document if document else "",
            next_action="Provide the compliance declaration signer.",
            severity="PENDING",
        )

    passed = names_match(submitted, document_signer)
    return _result(
        rule_code="COMPLIANCE_SIGNER",
        category="CONSISTENCY",
        passed=passed,
        message=(
            "Compliance declaration signer matches the submitted signer."
            if passed
            else "Compliance declaration signer does not match the submitted signer."
        ),
        submitted_value=submitted,
        reference_value=document_signer,
        source_document=document.source_document if document else "",
        next_action="" if passed else "Review the compliance declaration signer.",
        severity=None if passed else "PENDING",
    )


def compliance_date_rule(submission: VendorSubmission) -> ValidationResult:
    document = _document(submission, COMPLIANCE_DECLARATION)
    document_date = document.field("date") if document else None
    submitted = submission.compliance_date or ""
    passed = False
    if submitted and document_date:
        try:
            date.fromisoformat(submitted)
            date.fromisoformat(document_date)
            passed = submitted == document_date
        except ValueError:
            passed = False

    return _result(
        rule_code="COMPLIANCE_DATE",
        category="CONSISTENCY",
        passed=passed,
        message=(
            "Compliance declaration date is present, valid and consistent."
            if passed
            else "Compliance declaration date is missing, invalid or inconsistent."
        ),
        submitted_value=submitted,
        reference_value=document_date or "",
        source_document=document.source_document if document else "",
        next_action="" if passed else "Provide a matching ISO compliance declaration date.",
        severity=None if passed else "PENDING",
    )


def duplicate_tax_rule(
    submission: VendorSubmission,
    existing_submissions: Iterable[VendorSubmission],
) -> ValidationResult:
    current_tax_id = normalize_identifier(submission.gstin)
    conflicting_vendor: Optional[VendorSubmission] = None
    for existing in existing_submissions:
        if (
            current_tax_id
            and current_tax_id == normalize_identifier(existing.gstin)
            and not names_match(submission.legal_name, existing.legal_name)
        ):
            conflicting_vendor = existing
            break

    passed = conflicting_vendor is None
    return _result(
        rule_code="DUPLICATE_TAX_ID",
        category="RISK",
        passed=passed,
        message=(
            "Tax ID is not associated with another vendor identity."
            if passed
            else "Tax ID is associated with another vendor identity."
        ),
        submitted_value=submission.gstin,
        reference_value=conflicting_vendor.legal_name if conflicting_vendor else "",
        next_action="" if passed else "Reject and investigate the duplicate tax ID.",
        severity=None if passed else "REJECTED",
    )


def duplicate_bank_rule(
    submission: VendorSubmission,
    existing_submissions: Iterable[VendorSubmission],
) -> ValidationResult:
    current_account = normalize_identifier(submission.bank_account)
    conflicting_vendor: Optional[VendorSubmission] = None
    for existing in existing_submissions:
        if (
            current_account
            and current_account == normalize_identifier(existing.bank_account)
            and not names_match(submission.legal_name, existing.legal_name)
        ):
            conflicting_vendor = existing
            break

    passed = conflicting_vendor is None
    return _result(
        rule_code="DUPLICATE_BANK",
        category="RISK",
        passed=passed,
        message=(
            "Bank account is not associated with an unrelated vendor."
            if passed
            else "Bank account is already associated with an unrelated vendor."
        ),
        submitted_value=submission.bank_account,
        reference_value=conflicting_vendor.legal_name if conflicting_vendor else "",
        next_action="" if passed else "Reject and investigate the duplicate bank account.",
        severity=None if passed else "REJECTED",
    )


def blocklist_tax_rule(
    submission: VendorSubmission,
    blocklisted_tax_ids: Iterable[str],
) -> ValidationResult:
    current_tax_id = normalize_identifier(submission.gstin)
    blocklisted = {normalize_identifier(value) for value in blocklisted_tax_ids}
    passed = not current_tax_id or current_tax_id not in blocklisted
    return _result(
        rule_code="BLOCKLIST_TAX_ID",
        category="RISK",
        passed=passed,
        message=(
            "Tax ID is not on the synthetic blocklist."
            if passed
            else "Tax ID is on the synthetic blocklist."
        ),
        submitted_value=submission.gstin,
        reference_value="synthetic tax-ID blocklist",
        next_action="" if passed else "Reject and investigate the blocklisted tax ID.",
        severity=None if passed else "REJECTED",
    )


def blocklist_bank_rule(
    submission: VendorSubmission,
    blocklisted_bank_accounts: Iterable[str],
) -> ValidationResult:
    current_account = normalize_identifier(submission.bank_account)
    blocklisted = {normalize_identifier(value) for value in blocklisted_bank_accounts}
    passed = not current_account or current_account not in blocklisted
    return _result(
        rule_code="BLOCKLIST_BANK_ACCOUNT",
        category="RISK",
        passed=passed,
        message=(
            "Bank account is not on the synthetic blocklist."
            if passed
            else "Bank account is on the synthetic blocklist."
        ),
        submitted_value=submission.bank_account,
        reference_value="synthetic bank-account blocklist",
        next_action="" if passed else "Reject and investigate the blocklisted bank account.",
        severity=None if passed else "REJECTED",
    )


def evaluate_rules(
    submission: VendorSubmission,
    *,
    existing_submissions: Sequence[VendorSubmission] = (),
    blocklisted_tax_ids: Iterable[str] = (),
    blocklisted_bank_accounts: Iterable[str] = (),
) -> list[ValidationResult]:
    """Run every Phase 1 rule in a stable, explainable order."""

    results: list[ValidationResult] = []
    results.extend(required_field_rules(submission))
    results.append(document_required_rule(submission))
    results.extend(document_readable_rules(submission))
    results.extend(
        (
            gstin_structure_rule(submission),
            ifsc_structure_rule(submission),
            email_structure_rule(submission),
            legal_name_match_rule(submission),
            gstin_match_rule(submission),
            bank_name_match_rule(submission),
            compliance_signer_rule(submission),
            compliance_date_rule(submission),
            duplicate_tax_rule(submission, existing_submissions),
            duplicate_bank_rule(submission, existing_submissions),
            blocklist_tax_rule(submission, blocklisted_tax_ids),
            blocklist_bank_rule(submission, blocklisted_bank_accounts),
        )
    )
    return results