"""Decision aggregation for the VendorSure rules engine."""

from __future__ import annotations

from typing import Iterable, Sequence

from .models import APPROVED, PENDING, REJECTED, Decision, ValidationResult, VendorSubmission
from .rules import evaluate_rules


def aggregate_decision(results: Sequence[ValidationResult]) -> Decision:
    """Apply the documented REJECTED > PENDING > APPROVED precedence."""

    rejected = [result for result in results if not result.passed and result.severity == REJECTED]
    pending = [result for result in results if not result.passed and result.severity == PENDING]

    if rejected:
        status = REJECTED
        next_action = rejected[0].next_action or "Investigate the rejected validation results."
    elif pending:
        status = PENDING
        next_action = pending[0].next_action or "Provide the missing or unclear information."
    else:
        status = APPROVED
        next_action = "Vendor onboarding may proceed."

    return Decision(status=status, rule_results=tuple(results), next_action=next_action)


def evaluate_submission(
    submission: VendorSubmission,
    *,
    existing_submissions: Sequence[VendorSubmission] = (),
    blocklisted_tax_ids: Iterable[str] = (),
    blocklisted_bank_accounts: Iterable[str] = (),
) -> Decision:
    """Evaluate a submission using the shared rules engine."""

    results = evaluate_rules(
        submission,
        existing_submissions=existing_submissions,
        blocklisted_tax_ids=blocklisted_tax_ids,
        blocklisted_bank_accounts=blocklisted_bank_accounts,
    )
    return aggregate_decision(results)