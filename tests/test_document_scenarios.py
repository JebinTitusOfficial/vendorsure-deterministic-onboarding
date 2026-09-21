from dataclasses import replace
from pathlib import Path

from vendorsure.decisions import evaluate_submission
from vendorsure.demo_data import get_demo_scenarios
from vendorsure.extraction import (
    BANK_PROOF,
    COMPLIANCE_DECLARATION,
    TAX_CERTIFICATE,
    extract_document,
    to_document_evidence,
)
from vendorsure.models import DocumentEvidence
from vendorsure.rules import BANK_DOCUMENT, COMPLIANCE_DECLARATION as COMPLIANCE_RULE_DOCUMENT


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pdfs"


def load_evidence(filename: str, document_type: str) -> DocumentEvidence:
    result = extract_document(
        (FIXTURE_DIR / filename).read_bytes(),
        document_type,
        filename,
    )
    assert result.accepted
    assert result.readable
    assert not result.errors
    return to_document_evidence(result)


def test_generated_fixtures_drive_all_four_shared_engine_decisions():
    scenarios = {scenario.name: scenario for scenario in get_demo_scenarios()}
    document_sets = {
        "Apex Components Private Limited": (
            ("apex_tax_certificate.pdf", TAX_CERTIFICATE),
            ("apex_bank_proof.pdf", BANK_PROOF),
            ("apex_compliance_declaration.pdf", COMPLIANCE_DECLARATION),
        ),
        "Nova Industrial Services Private Limited": (
            ("nova_tax_certificate.pdf", TAX_CERTIFICATE),
            ("nova_bank_proof.pdf", BANK_PROOF),
            ("nova_compliance_declaration.pdf", COMPLIANCE_DECLARATION),
        ),
        "Orion Trading Company": (
            ("orion_tax_certificate.pdf", TAX_CERTIFICATE),
            ("orion_bank_proof.pdf", BANK_PROOF),
            ("orion_compliance_declaration.pdf", COMPLIANCE_DECLARATION),
        ),
        "BluePeak Logistics": (
            ("bluepeak_bank_proof.pdf", BANK_PROOF),
            ("bluepeak_compliance_declaration.pdf", COMPLIANCE_DECLARATION),
        ),
    }

    decisions = {}
    for name, files in document_sets.items():
        scenario = scenarios[name]
        evidence = tuple(load_evidence(filename, document_type) for filename, document_type in files)
        submission = replace(scenario.submission, documents=evidence)
        decisions[name] = evaluate_submission(
            submission,
            existing_submissions=scenario.existing_submissions,
            blocklisted_tax_ids=scenario.blocklisted_tax_ids,
            blocklisted_bank_accounts=scenario.blocklisted_bank_accounts,
        )

    assert decisions["Apex Components Private Limited"].status == "APPROVED"

    nova = decisions["Nova Industrial Services Private Limited"]
    assert nova.status == "PENDING"
    assert {result.rule_code for result in nova.failed_results} == {"BANK_NAME_MATCH"}

    orion = decisions["Orion Trading Company"]
    assert orion.status == "REJECTED"
    assert {result.rule_code for result in orion.failed_results} == {"DUPLICATE_BANK"}

    bluepeak = decisions["BluePeak Logistics"]
    assert bluepeak.status == "PENDING"
    assert {result.rule_code for result in bluepeak.failed_results} == {"DOC_REQUIRED"}


def test_blank_fixture_becomes_doc_readable_pending_rule_failure():
    result = extract_document(
        (FIXTURE_DIR / "unreadable_blank.pdf").read_bytes(),
        TAX_CERTIFICATE,
        "unreadable_blank.pdf",
    )
    evidence = result.to_document_evidence()
    scenario = next(
        scenario
        for scenario in get_demo_scenarios()
        if scenario.name == "Apex Components Private Limited"
    )
    decision = evaluate_submission(
        replace(scenario.submission, documents=(evidence,)),
    )

    readable_failures = [
        item
        for item in decision.failed_results
        if item.rule_code == "DOC_READABLE"
    ]
    assert decision.status == "PENDING"
    assert len(readable_failures) == 1
    assert readable_failures[0].severity == "PENDING"