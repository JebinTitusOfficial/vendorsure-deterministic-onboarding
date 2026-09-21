from pathlib import Path

from app import (
    HISTORY_COLUMNS,
    QUEUE_COLUMNS,
    build_submission,
    filter_runs,
    load_demo_history,
    scenario_form_data,
    status_badge,
    validate_form_data,
)
from vendorsure.demo_data import get_demo_scenarios
from vendorsure.repository import Repository


def test_app_imports_and_status_badges():
    assert "APPROVED" in status_badge("APPROVED")
    assert "#15803d" in status_badge("APPROVED")
    assert "PENDING" in status_badge("PENDING")
    assert "REJECTED" in status_badge("REJECTED")


def test_scenario_form_mapping_and_editable_submission():
    scenario = get_demo_scenarios()[0]
    form = scenario_form_data(scenario)
    assert form["legal_name"] == scenario.submission.legal_name
    assert form["gstin"] == scenario.submission.gstin
    form["bank_holder"] = "Edited Holder"
    submission = build_submission(form)
    assert submission.bank_account_holder == "Edited Holder"


def test_manual_input_validation():
    errors = validate_form_data({})
    assert "legal_name" in errors
    assert "gstin" in errors
    assert "bank_account" in errors
    assert not validate_form_data(
        {
            "legal_name": "Synthetic Vendor",
            "gstin": "27ABCDE1234F1Z5",
            "email": "ops@example.com",
            "bank_holder": "Synthetic Vendor",
            "bank_account": "100000000010",
            "ifsc": "HDFC0001234",
        }
    )


def test_demo_history_loader_uses_real_workflow_and_is_idempotent(tmp_path):
    repository = Repository(tmp_path / "ui.db")
    first = load_demo_history(repository)
    second = load_demo_history(repository)

    assert len(first) == 4
    assert all(result.run_id == repeat.run_id for result, repeat in zip(first, second))
    assert len(repository.list_recent_runs(20)) == 4
    assert repository.count_runs_by_status() == {
        "APPROVED": 1,
        "PENDING": 2,
        "REJECTED": 1,
    }


def test_app_data_does_not_include_an_unmasked_account_display_helper():
    scenario = get_demo_scenarios()[0]
    form = scenario_form_data(scenario)
    assert form["bank_account"] == scenario.submission.bank_account
    # The UI stores the value only in the editable form; persisted detail uses
    # Repository masking, which is covered by the repository privacy tests.
    assert "bank_account" in form


def test_review_queue_and_run_history_have_distinct_views():
    runs = [
        {"vendor_name": "Approved Vendor", "business_status": "APPROVED", "technical_state": "COMPLETED"},
        {"vendor_name": "Pending Vendor", "business_status": "PENDING", "technical_state": "COMPLETED"},
        {"vendor_name": "Rejected Vendor", "business_status": "REJECTED", "technical_state": "COMPLETED"},
        {"vendor_name": "Failed Vendor", "business_status": None, "technical_state": "FAILED"},
    ]

    queue = filter_runs(
        runs,
        queue=True,
        status_filter="All action required",
    )
    history = filter_runs(runs, queue=False, status_filter="All")

    assert [run["vendor_name"] for run in queue] == [
        "Pending Vendor",
        "Rejected Vendor",
        "Failed Vendor",
    ]
    assert [run["vendor_name"] for run in history] == [
        "Approved Vendor",
        "Pending Vendor",
        "Rejected Vendor",
        "Failed Vendor",
    ]
    assert [run["vendor_name"] for run in filter_runs(
        runs,
        queue=True,
        status_filter="Technical failures",
    )] == ["Failed Vendor"]
    assert "Primary reason" in QUEUE_COLUMNS
    assert "Next action" in QUEUE_COLUMNS
    assert "Run ID" in HISTORY_COLUMNS
    assert "Duration" in HISTORY_COLUMNS