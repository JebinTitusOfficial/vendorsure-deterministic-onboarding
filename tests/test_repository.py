import json

from vendorsure.demo_data import get_demo_scenarios
from vendorsure.repository import Repository, bank_account_fingerprint, mask_bank_account


def test_repository_schema_and_sensitive_bank_storage(tmp_path):
    database = tmp_path / "vendorsure.db"
    repository = Repository(database)
    scenario = get_demo_scenarios()[0]
    submission_id = repository.create_submission(scenario.submission)
    run_id = repository.create_processing_run(
        submission_id=submission_id,
        idempotency_key="repository-test",
        started_at="2026-01-01T00:00:00+00:00",
    )
    repository.save_documents(run_id, scenario.submission.documents)
    repository.close()

    reopened = Repository(database)
    submission = reopened.list_recent_submissions()[0]
    assert submission["masked_bank_account"] == mask_bank_account("100000000001")
    assert submission["bank_account_fingerprint"] == bank_account_fingerprint("100000000001")
    assert "100000000001" not in json.dumps(submission)
    documents = reopened.get_documents(run_id)
    assert all("100000000001" not in json.dumps(document) for document in documents)
    reopened.close()


def test_repository_queries_and_counts(tmp_path):
    repository = Repository(tmp_path / "queries.db")
    scenario = get_demo_scenarios()[0]
    submission_id = repository.create_submission(scenario.submission)
    run_id = repository.create_processing_run(
        submission_id=submission_id,
        idempotency_key=None,
        started_at="2026-01-01T00:00:00+00:00",
    )
    repository.update_run(
        run_id,
        technical_state="COMPLETED",
        business_status="APPROVED",
        primary_reason="ALL_CHECKS_PASSED",
        next_action="Proceed.",
        completed_at="2026-01-01T00:00:01+00:00",
        duration_ms=1000,
    )
    repository.add_audit_event(
        run_id,
        stage="FINALIZE",
        event_type="RUN_COMPLETED",
        message="done",
        duration_ms=1,
    )

    assert len(repository.list_recent_submissions()) == 1
    assert len(repository.filter_runs_by_business_status("APPROVED")) == 1
    assert repository.count_runs_by_status() == {
        "APPROVED": 1,
        "PENDING": 0,
        "REJECTED": 0,
    }
    detail = repository.get_complete_run_detail(run_id)
    assert detail["run"]["primary_reason"] == "ALL_CHECKS_PASSED"
    assert detail["audit_events"][0]["event_type"] == "RUN_COMPLETED"
    repository.close()