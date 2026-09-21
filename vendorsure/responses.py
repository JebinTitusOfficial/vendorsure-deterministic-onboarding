"""Fixed, rule-driven vendor response templates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .models import APPROVED, PENDING, REJECTED, Decision, ValidationResult


@dataclass(frozen=True)
class PreparedResponse:
    """A deterministic response ready to be shown or sent by a later UI."""

    subject: str
    body: str
    review_status: str


def _first_failed(
    results: Sequence[ValidationResult],
    *rule_codes: str,
) -> ValidationResult | None:
    for result in results:
        if not result.passed and result.rule_code in rule_codes:
            return result
    return None


def prepare_response(decision: Decision) -> PreparedResponse:
    """Assemble a response using only fixed templates and rule evidence."""

    if decision.status == APPROVED:
        return PreparedResponse(
            subject="VendorSure onboarding checks passed",
            body=(
                "The configured deterministic vendor-onboarding checks passed. "
                "Creation of the real vendor-master record is outside this prototype."
            ),
            review_status="NOT_REQUIRED",
        )

    if decision.status == REJECTED:
        duplicate_bank = _first_failed(decision.rule_results, "DUPLICATE_BANK")
        if duplicate_bank:
            body = (
                "Automatic onboarding has stopped because the bank account is "
                "associated with another vendor in the synthetic vendor master. "
                "Escalate this submission for manual fraud review."
            )
        else:
            risk = _first_failed(
                decision.rule_results,
                "DUPLICATE_TAX_ID",
                "BLOCKLIST_TAX_ID",
                "BLOCKLIST_BANK_ACCOUNT",
            )
            if risk:
                body = (
                    f"Automatic onboarding has stopped because the configured "
                    f"{risk.rule_code} control failed. Escalate this submission "
                    "for manual compliance review."
                )
            else:
                body = (
                    "Automatic onboarding has stopped because a configured risk "
                    "control failed. Escalate this submission for manual review."
                )
        return PreparedResponse(
            subject="VendorSure onboarding stopped",
            body=body,
            review_status="MANUAL_REVIEW_REQUIRED",
        )

    document = _first_failed(decision.rule_results, "DOC_REQUIRED")
    if document:
        missing_document = document.reference_value or "the required document"
        return PreparedResponse(
            subject="VendorSure information required",
            body=(
                f"Please provide the missing document: {missing_document}. "
                "Existing information has been retained."
            ),
            review_status="MANUAL_REVIEW_REQUIRED",
        )

    bank_name = _first_failed(decision.rule_results, "BANK_NAME_MATCH")
    if bank_name:
        return PreparedResponse(
            subject="VendorSure bank-holder clarification required",
            body=(
                f"The submitted bank-account holder name "
                f"'{bank_name.submitted_value}' was compared with "
                f"'{bank_name.reference_value}'. Please provide corrected bank "
                "proof or accepted trade-name evidence."
            ),
            review_status="MANUAL_REVIEW_REQUIRED",
        )

    invalid_format = _first_failed(
        decision.rule_results,
        "GSTIN_FORMAT",
        "IFSC_FORMAT",
    )
    if invalid_format:
        field_name = {
            "GSTIN_FORMAT": "GSTIN",
            "IFSC_FORMAT": "IFSC",
        }[invalid_format.rule_code]
        return PreparedResponse(
            subject="VendorSure field correction required",
            body=f"The submitted {field_name} has an invalid format. Please correct the {field_name}.",
            review_status="MANUAL_REVIEW_REQUIRED",
        )

    unreadable = _first_failed(decision.rule_results, "DOC_READABLE")
    if unreadable:
        return PreparedResponse(
            subject="VendorSure document review required",
            body=(
                "A submitted document could not be read as machine-readable PDF "
                "text. Please upload a readable PDF or provide it for manual review."
            ),
            review_status="MANUAL_REVIEW_REQUIRED",
        )

    first_failure = next(
        (result for result in decision.rule_results if not result.passed),
        None,
    )
    detail = first_failure.message if first_failure else "Additional information is required."
    return PreparedResponse(
        subject="VendorSure information required",
        body=f"{detail} Existing information has been retained.",
        review_status="MANUAL_REVIEW_REQUIRED",
    )