"""Typed domain models used by the VendorSure rules engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence


PENDING = "PENDING"
REJECTED = "REJECTED"
APPROVED = "APPROVED"


@dataclass(frozen=True)
class DocumentEvidence:
    """Evidence extracted from or supplied with one supporting document.

    PDF extraction is deliberately outside Phase 1.  The ``extracted_fields``
    mapping represents deterministic, already-available evidence that later
    adapters can populate.
    """

    document_type: str
    source_document: str
    extracted_fields: Mapping[str, str] = field(default_factory=dict)
    present: bool = True
    machine_readable: bool = True

    def field(self, name: str) -> Optional[str]:
        """Return a field from the document evidence, if it is available."""

        value = self.extracted_fields.get(name)
        return None if value is None else str(value)


@dataclass(frozen=True)
class VendorSubmission:
    """A vendor's submitted onboarding information.

    Original submitted values are retained as entered.  Rules use the
    normalization helpers only for comparisons and never mutate this object.
    """

    vendor_id: str
    legal_name: str
    gstin: str
    email: str
    ifsc: str
    bank_account: str
    bank_account_holder: str
    declared_trade_name: Optional[str] = None
    compliance_signer: Optional[str] = None
    compliance_date: Optional[str] = None
    documents: Sequence[DocumentEvidence] = field(default_factory=tuple)

    def document(self, document_type: str) -> Optional[DocumentEvidence]:
        """Return the first present document with the requested type."""

        for document in self.documents:
            if document.document_type == document_type and document.present:
                return document
        return None


@dataclass(frozen=True)
class ValidationResult:
    """The explainable result of one deterministic validation rule."""

    rule_code: str
    category: str
    passed: bool
    severity: Optional[str]
    message: str
    submitted_value: str
    reference_value: str
    source_document: str
    next_action: str
    rule_version: str

    def __post_init__(self) -> None:
        if self.passed and self.severity is not None:
            raise ValueError("A passed validation result cannot have a failure severity")
        if not self.passed and self.severity not in {PENDING, REJECTED}:
            raise ValueError("A failed validation result must be PENDING or REJECTED")


@dataclass(frozen=True)
class Decision:
    """The aggregate outcome of a rules-engine run."""

    status: str
    rule_results: Sequence[ValidationResult]
    next_action: str

    @property
    def failed_results(self) -> tuple[ValidationResult, ...]:
        """Return failed rules in their original evaluation order."""

        return tuple(result for result in self.rule_results if not result.passed)