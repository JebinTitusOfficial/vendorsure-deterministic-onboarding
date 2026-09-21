from vendorsure.models import Decision, ValidationResult
from vendorsure.responses import prepare_response


def result(code, *, passed=False, severity="PENDING", submitted="", reference="", message="failure"):
    return ValidationResult(
        rule_code=code,
        category="TEST",
        passed=passed,
        severity=None if passed else severity,
        message=message,
        submitted_value=submitted,
        reference_value=reference,
        source_document="test.pdf",
        next_action="Review.",
        rule_version="1.0",
    )


def decision(status, results=()):
    return Decision(status=status, rule_results=tuple(results), next_action="Review.")


def test_approved_template():
    response = prepare_response(decision("APPROVED"))
    assert response.review_status == "NOT_REQUIRED"
    assert "checks passed" in response.body
    assert "vendor-master" in response.body


def test_doc_required_template_names_document():
    response = prepare_response(
        decision("PENDING", [result("DOC_REQUIRED", reference="tax_certificate")])
    )
    assert "tax_certificate" in response.body
    assert "retained" in response.body


def test_bank_name_template_explains_both_names():
    response = prepare_response(
        decision(
            "PENDING",
            [
                result(
                    "BANK_NAME_MATCH",
                    submitted="Nova Services",
                    reference="Nova Industrial Services Private Limited",
                )
            ],
        )
    )
    assert "Nova Services" in response.body
    assert "Nova Industrial Services Private Limited" in response.body
    assert "trade-name evidence" in response.body


def test_invalid_gstin_and_ifsc_templates_name_the_field():
    gstin = prepare_response(decision("PENDING", [result("GSTIN_FORMAT")]))
    ifsc = prepare_response(decision("PENDING", [result("IFSC_FORMAT")]))
    assert "GSTIN" in gstin.body
    assert "IFSC" in ifsc.body


def test_rejected_templates_cover_duplicate_bank_and_risk_controls():
    bank = prepare_response(decision("REJECTED", [result("DUPLICATE_BANK", severity="REJECTED")]))
    risk = prepare_response(decision("REJECTED", [result("DUPLICATE_TAX_ID", severity="REJECTED")]))
    assert "automatic onboarding has stopped" in bank.body.lower()
    assert "fraud review" in bank.body.lower()
    assert "manual compliance review" in risk.body.lower()