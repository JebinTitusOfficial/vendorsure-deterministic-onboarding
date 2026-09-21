from vendorsure.decisions import aggregate_decision
from vendorsure.models import Decision, DocumentEvidence, VendorSubmission, ValidationResult
from vendorsure.normalization import normalize_name, normalize_text
from vendorsure.rules import (
    BANK_DOCUMENT,
    COMPLIANCE_DECLARATION,
    TAX_CERTIFICATE,
    bank_name_match_rule,
    blocklist_bank_rule,
    blocklist_tax_rule,
    compliance_date_rule,
    compliance_signer_rule,
    document_required_rule,
    duplicate_bank_rule,
    duplicate_tax_rule,
    email_structure_rule,
    evaluate_rules,
    gstin_match_rule,
    gstin_structure_rule,
    ifsc_structure_rule,
    legal_name_match_rule,
    required_field_rules,
)


def make_submission(**overrides) -> VendorSubmission:
    values = {
        "vendor_id": "test-vendor",
        "legal_name": "Apex Components Private Limited",
        "gstin": "27ABCDE1234F1Z5",
        "email": "ops@example.com",
        "ifsc": "HDFC0001234",
        "bank_account": "100000000001",
        "bank_account_holder": "Apex Components Pvt Ltd",
        "compliance_signer": "Authorized Signatory",
        "compliance_date": "2026-01-15",
        "documents": (
            DocumentEvidence(
                document_type=TAX_CERTIFICATE,
                source_document="tax.pdf",
                extracted_fields={
                    "legal_name": "Apex Components Pvt Ltd",
                    "gstin": "27ABCDE1234F1Z5",
                },
            ),
            DocumentEvidence(
                document_type=BANK_DOCUMENT,
                source_document="bank.pdf",
                extracted_fields={"account_holder": "Apex Components Pvt Ltd"},
            ),
            DocumentEvidence(
                document_type=COMPLIANCE_DECLARATION,
                source_document="compliance.pdf",
                extracted_fields={"signer": "Authorized Signatory", "date": "2026-01-15"},
            ),
        ),
    }
    values.update(overrides)
    return VendorSubmission(**values)


def result(results, code):
    return next(item for item in results if item.rule_code == code)


def test_name_normalization_is_exact_and_removes_legal_suffix():
    assert normalize_name("Apex Components, Private Limited") == "apex components"
    assert normalize_name("APEX COMPONENTS PVT LTD") == "apex components"
    assert normalize_text("  A/B   C  ") == "a b c"
    assert normalize_name("Apex Component") != normalize_name("Apex Components")


def test_gstin_validation_is_structure_only():
    assert gstin_structure_rule(make_submission()).passed
    assert not gstin_structure_rule(make_submission(gstin="not-a-gstin")).passed


def test_ifsc_validation_is_structure_only():
    assert ifsc_structure_rule(make_submission()).passed
    assert not ifsc_structure_rule(make_submission(ifsc="BAD123")).passed


def test_required_field_rules_return_pending_for_missing_values():
    results = required_field_rules(make_submission(email=""))
    email_result = result(results, "REQUIRED_EMAIL")
    assert not email_result.passed
    assert email_result.severity == "PENDING"


def test_document_required_rule():
    missing = make_submission(documents=())
    check = document_required_rule(missing)
    assert not check.passed
    assert check.rule_code == "DOC_REQUIRED"
    assert check.severity == "PENDING"


def test_email_rule():
    from vendorsure.rules import email_structure_rule

    assert email_structure_rule(make_submission()).passed
    assert not email_structure_rule(make_submission(email="invalid")).passed


def test_legal_name_match_rule():
    assert legal_name_match_rule(make_submission()).passed
    result_value = legal_name_match_rule(
        make_submission(
            documents=(
                DocumentEvidence(
                    document_type=TAX_CERTIFICATE,
                    source_document="tax.pdf",
                    extracted_fields={
                        "legal_name": "Different Vendor",
                        "gstin": "27ABCDE1234F1Z5",
                    },
                ),
            )
        )
    )
    assert not result_value.passed
    assert result_value.severity == "PENDING"


def test_gstin_match_rule():
    assert gstin_match_rule(make_submission()).passed
    assert not gstin_match_rule(
        make_submission(
            documents=(
                DocumentEvidence(
                    document_type=TAX_CERTIFICATE,
                    source_document="tax.pdf",
                    extracted_fields={
                        "legal_name": "Apex Components Pvt Ltd",
                        "gstin": "29OTHER1234A1Z2",
                    },
                ),
            )
        )
    ).passed


def test_bank_name_match_accepts_declared_trade_name():
    assert not bank_name_match_rule(
        make_submission(bank_account_holder="Apex Trade")
    ).passed
    assert bank_name_match_rule(
        make_submission(
            bank_account_holder="Apex Trade",
            declared_trade_name="Apex Trade",
        )
    ).passed


def test_compliance_signer_and_date_rules():
    assert compliance_signer_rule(make_submission()).passed
    assert compliance_date_rule(make_submission()).passed
    assert not compliance_signer_rule(make_submission(compliance_signer="Other Signer")).passed
    assert not compliance_date_rule(make_submission(compliance_date="15/01/2026")).passed


def test_duplicate_tax_id_rejects_only_an_unrelated_identity():
    existing = make_submission(vendor_id="other", legal_name="Different Vendor")
    check = duplicate_tax_rule(make_submission(), [existing])
    assert not check.passed
    assert check.severity == "REJECTED"
    assert duplicate_tax_rule(make_submission(), [make_submission(vendor_id="same")]).passed


def test_duplicate_bank_rejects_only_an_unrelated_identity():
    existing = make_submission(vendor_id="other", legal_name="Different Vendor")
    check = duplicate_bank_rule(make_submission(), [existing])
    assert not check.passed
    assert check.rule_code == "DUPLICATE_BANK"
    assert check.severity == "REJECTED"


def test_blocklist_rules_are_rejected():
    submission = make_submission()
    assert blocklist_tax_rule(submission, [submission.gstin]).severity == "REJECTED"
    assert blocklist_bank_rule(submission, [submission.bank_account]).severity == "REJECTED"
    assert blocklist_tax_rule(submission, []).passed
    assert blocklist_bank_rule(submission, []).passed


def test_evaluate_rules_includes_all_rule_categories():
    results = evaluate_rules(make_submission())
    codes = {item.rule_code for item in results}
    assert {
        "REQUIRED_LEGAL_NAME",
        "DOC_REQUIRED",
        "GSTIN_FORMAT",
        "IFSC_FORMAT",
        "EMAIL_FORMAT",
        "LEGAL_NAME_MATCH",
        "GSTIN_MATCH",
        "BANK_NAME_MATCH",
        "COMPLIANCE_SIGNER",
        "COMPLIANCE_DATE",
        "DUPLICATE_TAX_ID",
        "DUPLICATE_BANK",
        "BLOCKLIST_TAX_ID",
        "BLOCKLIST_BANK_ACCOUNT",
    }.issubset(codes)


def test_decision_precedence_rejected_then_pending_then_approved():
    pending = ValidationResult(
        rule_code="PENDING_RULE",
        category="FORMAT",
        passed=False,
        severity="PENDING",
        message="needs review",
        submitted_value="",
        reference_value="",
        source_document="",
        next_action="Provide information.",
        rule_version="1.0",
    )
    rejected = ValidationResult(
        rule_code="REJECTED_RULE",
        category="RISK",
        passed=False,
        severity="REJECTED",
        message="blocked",
        submitted_value="",
        reference_value="",
        source_document="",
        next_action="Investigate.",
        rule_version="1.0",
    )
    passed = ValidationResult(
        rule_code="PASS_RULE",
        category="FORMAT",
        passed=True,
        severity=None,
        message="ok",
        submitted_value="",
        reference_value="",
        source_document="",
        next_action="",
        rule_version="1.0",
    )

    assert aggregate_decision([passed]).status == "APPROVED"
    assert aggregate_decision([pending]).status == "PENDING"
    assert aggregate_decision([pending, rejected]).status == "REJECTED"