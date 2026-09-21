from dataclasses import replace
from pathlib import Path

from vendorsure.demo_data import get_demo_scenarios
from vendorsure.repository import Repository
from vendorsure.workflow import COMPLETED, FAILED, WORKFLOW_STAGES, WorkflowService


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pdfs"


def scenario_inputs(scenario):
    prefix = {
        "Apex Components Private Limited": "apex",
        "Nova Industrial Services Private Limited": "nova",
        "Orion Trading Company": "orion",
        "BluePeak Logistics": "bluepeak",
    }[scenario.name]
    documents = {
        "BANK_PROOF": (
            f"{prefix}_bank_proof.pdf",
            (FIXTURE_DIR / f"{prefix}_bank_proof.pdf").read_bytes(),
        ),
        "COMPLIANCE_DECLARATION": (
            f"{prefix}_compliance_declaration.pdf",
            (FIXTURE_DIR / f"{prefix}_compliance_declaration.pdf").read_bytes(),
        ),
    }
    if scenario.name != "BluePeak Logistics":
        documents["TAX_CERTIFICATE"] = (
            f"{prefix}_tax_certificate.pdf",
            (FIXTURE_DIR / f"{prefix}_tax_certificate.pdf").read_bytes(),
        )
    return documents


def test_complete_workflow_has_real_stages_and_nonnegative_durations(tmp_path):
    scenario = get_demo_scenarios()[0]
    repository = Repository(tmp_path / "workflow.db")
    result = WorkflowService(repository).run(
        scenario.submission,
        scenario_inputs(scenario),
        idempotency_key="apex-run",
    )

    assert result.technical_state == COMPLETED
    assert result.business_status == "APPROVED"
    assert tuple(stage.stage for stage in result.stage_results) == WORKFLOW_STAGES
    assert all(stage.success and stage.duration_ms >= 0 for stage in result.stage_results)
    assert result.response.subject == "VendorSure onboarding checks passed"

    events = repository.get_audit_events(result.run_id)
    assert events[0]["event_type"] == "SUBMISSION_RECEIVED"
    assert events[-1]["event_type"] == "RUN_COMPLETED"
    assert [event["event_type"] for event in events].count("RULE_EVALUATED") > 0


def test_all_four_pdf_backed_workflows_keep_expected_decisions(tmp_path):
    repository = Repository(tmp_path / "scenarios.db")
    service = WorkflowService(repository)
    results = {}
    for scenario in get_demo_scenarios():
        results[scenario.name] = service.run(
            scenario.submission,
            scenario_inputs(scenario),
            idempotency_key=f"key-{scenario.submission.vendor_id}",
            existing_submissions=scenario.existing_submissions,
        )

    assert results["Apex Components Private Limited"].business_status == "APPROVED"
    assert results["Nova Industrial Services Private Limited"].business_status == "PENDING"
    assert results["Nova Industrial Services Private Limited"].primary_reason == "BANK_NAME_MATCH"
    assert results["Orion Trading Company"].business_status == "REJECTED"
    assert results["Orion Trading Company"].primary_reason == "DUPLICATE_BANK"
    assert results["BluePeak Logistics"].business_status == "PENDING"
    assert results["BluePeak Logistics"].primary_reason == "DOC_REQUIRED"


def test_idempotency_reuses_existing_run_and_new_key_creates_new_run(tmp_path):
    scenario = get_demo_scenarios()[0]
    repository = Repository(tmp_path / "idempotency.db")
    service = WorkflowService(repository)
    first = service.run(scenario.submission, scenario_inputs(scenario), idempotency_key="same")
    second = service.run(scenario.submission, scenario_inputs(scenario), idempotency_key="same")
    third = service.run(scenario.submission, scenario_inputs(scenario), idempotency_key="new")

    assert second.run_id == first.run_id
    assert second.reused_existing
    assert third.run_id != first.run_id
    assert len(repository.filter_runs_by_business_status("APPROVED")) == 2


def test_technical_extraction_failure_is_failed_not_business_decision(tmp_path):
    scenario = get_demo_scenarios()[0]
    repository = Repository(tmp_path / "failure.db")

    class BrokenUpload:
        name = "broken.pdf"

        def read(self):
            raise OSError("synthetic read failure")

    result = WorkflowService(repository).run(
        scenario.submission,
        {"TAX_CERTIFICATE": BrokenUpload()},
    )

    assert result.technical_state == FAILED
    assert result.business_status is None
    assert result.response is None
    assert result.error.startswith("RuntimeError:")
    events = repository.get_audit_events(result.run_id)
    assert events[-1]["event_type"] == "RUN_FAILED"
    assert repository.get_run(result.run_id)["business_status"] is None


def test_raw_pdfs_complete_text_and_unmasked_bank_are_not_persisted(tmp_path):
    scenario = get_demo_scenarios()[0]
    repository = Repository(tmp_path / "privacy.db")
    result = WorkflowService(repository).run(scenario.submission, scenario_inputs(scenario))
    detail = repository.get_complete_run_detail(result.run_id)
    serialized = repr(detail)

    assert b"%PDF-" not in serialized.encode()
    assert "LEGAL NAME: Apex Components Private Limited" not in serialized
    assert "100000000001" not in serialized
    assert "********0001" in serialized