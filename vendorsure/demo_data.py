"""Synthetic VendorSure scenarios for deterministic demonstrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .models import DocumentEvidence, VendorSubmission
from .rules import BANK_DOCUMENT, COMPLIANCE_DECLARATION, TAX_CERTIFICATE


@dataclass(frozen=True)
class DemoScenario:
    """Inputs and reference data for one synthetic demonstration."""

    name: str
    submission: VendorSubmission
    existing_submissions: Sequence[VendorSubmission] = ()
    blocklisted_tax_ids: Sequence[str] = ()
    blocklisted_bank_accounts: Sequence[str] = ()


def _documents(
    *,
    legal_name: str,
    gstin: str,
    signer: str,
    compliance_date: str,
    bank_holder: str,
) -> tuple[DocumentEvidence, ...]:
    return (
        DocumentEvidence(
            document_type=TAX_CERTIFICATE,
            source_document="synthetic_tax_certificate.pdf",
            extracted_fields={"legal_name": legal_name, "gstin": gstin},
        ),
        DocumentEvidence(
            document_type=BANK_DOCUMENT,
            source_document="synthetic_bank_letter.pdf",
            extracted_fields={"account_holder": bank_holder},
        ),
        DocumentEvidence(
            document_type=COMPLIANCE_DECLARATION,
            source_document="synthetic_compliance_declaration.pdf",
            extracted_fields={"signer": signer, "date": compliance_date},
        ),
    )


def _submission(
    *,
    vendor_id: str,
    legal_name: str,
    gstin: str,
    email: str,
    ifsc: str,
    bank_account: str,
    bank_account_holder: str,
    declared_trade_name: str | None = None,
    compliance_signer: str = "Authorized Signatory",
    compliance_date: str = "2026-01-15",
    documents: Sequence[DocumentEvidence] = (),
) -> VendorSubmission:
    return VendorSubmission(
        vendor_id=vendor_id,
        legal_name=legal_name,
        gstin=gstin,
        email=email,
        ifsc=ifsc,
        bank_account=bank_account,
        bank_account_holder=bank_account_holder,
        declared_trade_name=declared_trade_name,
        compliance_signer=compliance_signer,
        compliance_date=compliance_date,
        documents=documents,
    )


def get_demo_scenarios() -> tuple[DemoScenario, ...]:
    """Return the four prepared scenarios without precomputed outcomes."""

    apex = _submission(
        vendor_id="demo-apex",
        legal_name="Apex Components Private Limited",
        gstin="27ABCDE1234F1Z5",
        email="ops@apex-components.example",
        ifsc="HDFC0001234",
        bank_account="100000000001",
        bank_account_holder="Apex Components Pvt Ltd",
        compliance_signer="Authorized Signatory",
        documents=_documents(
            legal_name="Apex Components Pvt Ltd",
            gstin="27ABCDE1234F1Z5",
            signer="Authorized Signatory",
            compliance_date="2026-01-15",
            bank_holder="Apex Components Pvt Ltd",
        ),
    )

    nova = _submission(
        vendor_id="demo-nova",
        legal_name="Nova Industrial Services Private Limited",
        gstin="29NOVAQ1234G1Z6",
        email="ops@nova-industrial.example",
        ifsc="ICIC0005678",
        bank_account="100000000002",
        bank_account_holder="Nova Services",
        documents=_documents(
            legal_name="Nova Industrial Services Private Limited",
            gstin="29NOVAQ1234G1Z6",
            signer="Authorized Signatory",
            compliance_date="2026-01-15",
            bank_holder="Nova Services",
        ),
    )

    existing_orion_vendor = _submission(
        vendor_id="existing-related-vendor",
        legal_name="Harbor Trading Private Limited",
        gstin="07HARBQ1234H1Z7",
        email="ops@harbor-trading.example",
        ifsc="SBIN0009999",
        bank_account="100000000003",
        bank_account_holder="Harbor Trading Pvt Ltd",
        documents=(),
    )
    orion = _submission(
        vendor_id="demo-orion",
        legal_name="Orion Trading Company",
        gstin="24ORION1234J1Z8",
        email="ops@orion-trading.example",
        ifsc="AXIS0004321",
        bank_account="100000000003",
        bank_account_holder="Orion Trading Company",
        documents=_documents(
            legal_name="Orion Trading Company",
            gstin="24ORION1234J1Z8",
            signer="Authorized Signatory",
            compliance_date="2026-01-15",
            bank_holder="Orion Trading Company",
        ),
    )

    bluepeak = _submission(
        vendor_id="demo-bluepeak",
        legal_name="BluePeak Logistics",
        gstin="19BLUEP1234K1Z9",
        email="ops@bluepeak-logistics.example",
        ifsc="YESB0002468",
        bank_account="100000000004",
        bank_account_holder="BluePeak Logistics",
        documents=(
            DocumentEvidence(
                document_type=BANK_DOCUMENT,
                source_document="synthetic_bank_letter.pdf",
                extracted_fields={"account_holder": "BluePeak Logistics"},
            ),
            DocumentEvidence(
                document_type=COMPLIANCE_DECLARATION,
                source_document="synthetic_compliance_declaration.pdf",
                extracted_fields={
                    "signer": "Authorized Signatory",
                    "date": "2026-01-15",
                },
            ),
        ),
    )

    return (
        DemoScenario(name="Apex Components Private Limited", submission=apex),
        DemoScenario(name="Nova Industrial Services Private Limited", submission=nova),
        DemoScenario(
            name="Orion Trading Company",
            submission=orion,
            existing_submissions=(existing_orion_vendor,),
        ),
        DemoScenario(name="BluePeak Logistics", submission=bluepeak),
    )