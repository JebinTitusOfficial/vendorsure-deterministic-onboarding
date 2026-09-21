"""Seven-stage deterministic VendorSure workflow orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, BinaryIO, Callable, Mapping, Optional, Sequence

from .decisions import aggregate_decision
from .extraction import ExtractionResult, extract_document
from .models import Decision, VendorSubmission
from .repository import RULESET_VERSION, Repository
from .responses import PreparedResponse, prepare_response
from .rules import evaluate_rules


RECEIVED = "RECEIVED"
PROCESSING = "PROCESSING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"

WORKFLOW_STAGES = (
    "INTAKE",
    "EXTRACT",
    "NORMALIZE",
    "VALIDATE",
    "DECIDE",
    "PREPARE_RESPONSE",
    "FINALIZE",
)


@dataclass(frozen=True)
class UploadedDocument:
    """An explicitly selected document and its uploaded content."""

    document_type: str
    content: bytes | bytearray | BinaryIO | None
    filename: Optional[str] = None


@dataclass(frozen=True)
class StageResult:
    stage: str
    started_at: str
    completed_at: str
    duration_ms: float
    success: bool
    summary: str
    error: Optional[str] = None


@dataclass(frozen=True)
class ProgressEvent:
    """A UI-safe notification emitted at stage boundaries."""

    stage: str
    event_type: str
    summary: str
    duration_ms: Optional[float] = None
    success: Optional[bool] = None


@dataclass(frozen=True)
class WorkflowResult:
    run_id: str
    submission_id: str
    technical_state: str
    business_status: Optional[str]
    primary_reason: Optional[str]
    next_action: Optional[str]
    stage_results: Sequence[StageResult]
    response: Optional[PreparedResponse]
    reused_existing: bool = False
    error: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error(error: Exception) -> str:
    return f"{type(error).__name__}: {str(error)[:240]}"


class WorkflowService:
    """Coordinates extraction, existing rules, responses and persistence."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    @staticmethod
    def _coerce_documents(
        uploaded_documents: Mapping[str, Any] | Sequence[UploadedDocument] | None,
    ) -> tuple[UploadedDocument, ...]:
        if uploaded_documents is None:
            return ()
        if isinstance(uploaded_documents, Mapping):
            result = []
            for document_type, value in uploaded_documents.items():
                if isinstance(value, UploadedDocument):
                    result.append(value)
                elif (
                    isinstance(value, tuple)
                    and len(value) == 2
                    and isinstance(value[0], str)
                ):
                    result.append(
                        UploadedDocument(
                            document_type=str(document_type),
                            filename=value[0],
                            content=value[1],
                        )
                    )
                else:
                    result.append(
                        UploadedDocument(
                            document_type=str(document_type),
                            filename=getattr(value, "name", None),
                            content=value,
                        )
                    )
            return tuple(result)
        return tuple(uploaded_documents)

    def _existing_result(self, run_id: str) -> WorkflowResult:
        detail = self.repository.get_complete_run_detail(run_id)
        if detail is None:
            raise ValueError(f"Idempotent run {run_id} no longer exists")
        run = detail["run"]
        response_row = detail["response"]
        response = (
            PreparedResponse(
                subject=response_row["subject"],
                body=response_row["body"],
                review_status=response_row["review_status"],
            )
            if response_row
            else None
        )
        stages: list[StageResult] = []
        starts: dict[str, dict[str, Any]] = {}
        for event in detail["audit_events"]:
            if event["event_type"] == "STAGE_STARTED":
                starts[event["stage"]] = event
            elif event["event_type"] == "STAGE_COMPLETED" and event["stage"] in starts:
                start = starts[event["stage"]]
                stages.append(
                    StageResult(
                        stage=event["stage"],
                        started_at=start["created_at"],
                        completed_at=event["created_at"],
                        duration_ms=float(event["duration_ms"] or 0),
                        success=True,
                        summary=event["message"],
                    )
                )
        return WorkflowResult(
            run_id=run_id,
            submission_id=run["submission_id"],
            technical_state=run["technical_state"],
            business_status=run["business_status"],
            primary_reason=run["primary_reason"],
            next_action=run["next_action"],
            stage_results=tuple(stages),
            response=response,
            reused_existing=True,
        )

    def run(
        self,
        submission: VendorSubmission,
        uploaded_documents: Mapping[str, Any] | Sequence[UploadedDocument] | None = None,
        *,
        idempotency_key: Optional[str] = None,
        existing_submissions: Sequence[VendorSubmission] = (),
        blocklisted_tax_ids: Sequence[str] = (),
        blocklisted_bank_accounts: Sequence[str] = (),
        progress_callback: Optional[Callable[[ProgressEvent], None]] = None,
    ) -> WorkflowResult:
        """Run a submission through all seven real stages."""

        if idempotency_key:
            existing_run = self.repository.find_run_by_idempotency_key(idempotency_key)
            if existing_run:
                return self._existing_result(existing_run["id"])

        uploads = self._coerce_documents(uploaded_documents)
        started_at = _now()
        submission_id = self.repository.create_submission(submission)
        run_id = self.repository.create_processing_run(
            submission_id=submission_id,
            idempotency_key=idempotency_key,
            started_at=started_at,
        )
        self.repository.add_audit_event(
            run_id,
            stage="INTAKE",
            event_type="SUBMISSION_RECEIVED",
            message="Vendor submission received.",
        )
        stage_results: list[StageResult] = []
        extraction_results: tuple[ExtractionResult, ...] = ()
        normalized_submission = submission
        decision: Optional[Decision] = None
        response: Optional[PreparedResponse] = None
        current_stage = "INTAKE"
        run_clock = time.perf_counter()

        def notify(event: ProgressEvent) -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(event)
            except Exception:
                # A presentation callback must never change a business result.
                pass

        def execute_stage(stage: str, function):
            nonlocal current_stage
            current_stage = stage
            stage_started_at = _now()
            stage_clock = time.perf_counter()
            self.repository.update_run(run_id, technical_state=PROCESSING)
            self.repository.add_audit_event(
                run_id,
                stage=stage,
                event_type="STAGE_STARTED",
                message=f"{stage} stage started.",
            )
            notify(
                ProgressEvent(
                    stage=stage,
                    event_type="STAGE_STARTED",
                    summary=f"{stage} stage started.",
                )
            )
            try:
                output, summary = function()
                duration_ms = round(max(0.0, time.perf_counter() - stage_clock) * 1000, 3)
                completed_at = _now()
                self.repository.add_audit_event(
                    run_id,
                    stage=stage,
                    event_type="STAGE_COMPLETED",
                    message=summary,
                    duration_ms=duration_ms,
                )
                notify(
                    ProgressEvent(
                        stage=stage,
                        event_type="STAGE_COMPLETED",
                        summary=summary,
                        duration_ms=duration_ms,
                        success=True,
                    )
                )
                stage_results.append(
                    StageResult(
                        stage=stage,
                        started_at=stage_started_at,
                        completed_at=completed_at,
                        duration_ms=duration_ms,
                        success=True,
                        summary=summary,
                    )
                )
                return output
            except Exception as error:
                duration_ms = round(max(0.0, time.perf_counter() - stage_clock) * 1000, 3)
                safe_error = _safe_error(error)
                self.repository.add_audit_event(
                    run_id,
                    stage=stage,
                    event_type="RUN_FAILED",
                    message=safe_error,
                    duration_ms=duration_ms,
                )
                notify(
                    ProgressEvent(
                        stage=stage,
                        event_type="RUN_FAILED",
                        summary=safe_error,
                        duration_ms=duration_ms,
                        success=False,
                    )
                )
                self.repository.update_run(
                    run_id,
                    technical_state=FAILED,
                    completed_at=_now(),
                    duration_ms=round(max(0.0, time.perf_counter() - run_clock) * 1000, 3),
                )
                stage_results.append(
                    StageResult(
                        stage=stage,
                        started_at=stage_started_at,
                        completed_at=_now(),
                        duration_ms=duration_ms,
                        success=False,
                        summary=f"{stage} stage failed.",
                        error=safe_error,
                    )
                )
                raise

        try:
            execute_stage(
                "INTAKE",
                lambda: (
                    uploads,
                    f"Accepted submission with {len(uploads)} user-selected document(s).",
                ),
            )

            def extract_stage():
                results = []
                for upload in uploads:
                    result = extract_document(
                        upload.content,
                        upload.document_type,
                        upload.filename,
                    )
                    if not result.accepted:
                        raise RuntimeError(
                            f"Document {result.source_filename} was not accepted: "
                            f"{'; '.join(result.errors)}"
                        )
                    results.append(result)
                return tuple(results), f"Extracted {len(results)} document(s)."

            extraction_results = execute_stage("EXTRACT", extract_stage)

            def normalize_stage():
                evidence = tuple(result.to_document_evidence() for result in extraction_results)
                return replace(normalized_submission, documents=evidence), (
                    f"Normalized {len(evidence)} document evidence record(s)."
                )

            normalized_submission = execute_stage("NORMALIZE", normalize_stage)

            def validate_stage():
                results = evaluate_rules(
                    normalized_submission,
                    existing_submissions=existing_submissions,
                    blocklisted_tax_ids=blocklisted_tax_ids,
                    blocklisted_bank_accounts=blocklisted_bank_accounts,
                )
                self.repository.save_documents(run_id, extraction_results)
                self.repository.save_rule_results(run_id, results)
                for result in results:
                    self.repository.add_audit_event(
                        run_id,
                        stage="VALIDATE",
                        event_type="RULE_EVALUATED",
                        message=f"{result.rule_code}: {'PASS' if result.passed else 'FAIL'}",
                    )
                return results, f"Evaluated {len(results)} deterministic rule(s)."

            validation_results = execute_stage("VALIDATE", validate_stage)

            def decide_stage():
                result = aggregate_decision(validation_results)
                self.repository.update_run(
                    run_id,
                    business_status=result.status,
                    primary_reason=(
                        result.failed_results[0].rule_code
                        if result.failed_results
                        else "ALL_CHECKS_PASSED"
                    ),
                    next_action=result.next_action,
                )
                self.repository.add_audit_event(
                    run_id,
                    stage="DECIDE",
                    event_type="DECISION_CREATED",
                    message=f"Business decision created: {result.status}.",
                )
                return result, f"Created business decision: {result.status}."

            decision = execute_stage("DECIDE", decide_stage)

            def response_stage():
                prepared = prepare_response(decision)
                self.repository.save_response(
                    run_id,
                    subject=prepared.subject,
                    body=prepared.body,
                    review_status=prepared.review_status,
                )
                self.repository.add_audit_event(
                    run_id,
                    stage="PREPARE_RESPONSE",
                    event_type="RESPONSE_PREPARED",
                    message=f"Prepared response: {prepared.subject}.",
                )
                return prepared, f"Prepared deterministic response: {prepared.subject}."

            response = execute_stage("PREPARE_RESPONSE", response_stage)

            def finalize_stage():
                self.repository.update_run(
                    run_id,
                    technical_state=COMPLETED,
                    completed_at=_now(),
                    duration_ms=round(max(0.0, time.perf_counter() - run_clock) * 1000, 3),
                )
                return True, "Persisted completed workflow run."

            execute_stage("FINALIZE", finalize_stage)
            self.repository.add_audit_event(
                run_id,
                stage="FINALIZE",
                event_type="RUN_COMPLETED",
                message="Workflow run completed.",
            )
        except Exception as error:
            detail = self.repository.get_run(run_id) or {}
            return WorkflowResult(
                run_id=run_id,
                submission_id=submission_id,
                technical_state=FAILED,
                business_status=None,
                primary_reason=None,
                next_action="Correct the technical input and retry the workflow.",
                stage_results=tuple(stage_results),
                response=None,
                error=_safe_error(error),
            )

        return WorkflowResult(
            run_id=run_id,
            submission_id=submission_id,
            technical_state=COMPLETED,
            business_status=decision.status if decision else None,
            primary_reason=(
                decision.failed_results[0].rule_code
                if decision and decision.failed_results
                else "ALL_CHECKS_PASSED"
            ),
            next_action=decision.next_action if decision else None,
            stage_results=tuple(stage_results),
            response=response,
        )


def process_submission(
    repository: Repository,
    submission: VendorSubmission,
    uploaded_documents: Mapping[str, Any] | Sequence[UploadedDocument] | None = None,
    *,
    idempotency_key: Optional[str] = None,
    existing_submissions: Sequence[VendorSubmission] = (),
    progress_callback: Optional[Callable[[ProgressEvent], None]] = None,
) -> WorkflowResult:
    """Convenience function for one workflow run."""

    return WorkflowService(repository).run(
        submission,
        uploaded_documents,
        idempotency_key=idempotency_key,
        existing_submissions=existing_submissions,
        progress_callback=progress_callback,
    )