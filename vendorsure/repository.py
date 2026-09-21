"""SQLite persistence for VendorSure workflow runs."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from .models import DocumentEvidence, ValidationResult, VendorSubmission
from .normalization import normalize_identifier, normalize_name


RULESET_VERSION = "1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def mask_bank_account(value: str) -> str:
    normalized = normalize_identifier(value)
    if not normalized:
        return ""
    return ("*" * max(0, len(normalized) - 4)) + normalized[-4:]


def bank_account_fingerprint(value: str) -> str:
    normalized = normalize_identifier(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class Repository:
    """Small repository with parameterized queries and explicit transactions."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self.database = str(database)
        self.connection = sqlite3.connect(self.database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.create_schema()

    def create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                vendor_name TEXT NOT NULL,
                normalized_vendor_name TEXT NOT NULL,
                tax_id TEXT NOT NULL,
                masked_bank_account TEXT NOT NULL,
                bank_account_fingerprint TEXT NOT NULL,
                contact_email TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS processing_runs (
                id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL REFERENCES submissions(id),
                idempotency_key TEXT,
                technical_state TEXT NOT NULL,
                business_status TEXT,
                primary_reason TEXT,
                next_action TEXT,
                ruleset_version TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                duration_ms REAL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_processing_runs_idempotency
                ON processing_runs(idempotency_key)
                WHERE idempotency_key IS NOT NULL;

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES processing_runs(id),
                document_type TEXT NOT NULL,
                sanitized_filename TEXT NOT NULL,
                sha256_hash TEXT,
                extraction_status TEXT NOT NULL,
                extracted_fields_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rule_results (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES processing_runs(id),
                rule_code TEXT NOT NULL,
                category TEXT NOT NULL,
                passed INTEGER NOT NULL,
                severity TEXT,
                message TEXT NOT NULL,
                submitted_value TEXT NOT NULL,
                reference_value TEXT NOT NULL,
                source_document TEXT NOT NULL,
                next_action TEXT NOT NULL,
                rule_version TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS communications (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES processing_runs(id),
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                review_status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES processing_runs(id),
                stage TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                duration_ms REAL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def create_submission(self, submission: VendorSubmission) -> str:
        submission_id = new_id()
        self.connection.execute(
            """
            INSERT INTO submissions (
                id, vendor_name, normalized_vendor_name, tax_id,
                masked_bank_account, bank_account_fingerprint,
                contact_email, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                submission.legal_name,
                normalize_name(submission.legal_name),
                normalize_identifier(submission.gstin),
                mask_bank_account(submission.bank_account),
                bank_account_fingerprint(submission.bank_account),
                submission.email,
                utc_now(),
            ),
        )
        self.connection.commit()
        return submission_id

    def create_reference_submission(self, submission: VendorSubmission) -> str:
        """Persist a seeded vendor record without creating a processing run."""

        return self.create_submission(submission)

    def create_processing_run(
        self,
        *,
        submission_id: str,
        idempotency_key: Optional[str],
        started_at: str,
        technical_state: str = "RECEIVED",
    ) -> str:
        run_id = new_id()
        self.connection.execute(
            """
            INSERT INTO processing_runs (
                id, submission_id, idempotency_key, technical_state,
                business_status, primary_reason, next_action,
                ruleset_version, started_at
            ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
            """,
            (
                run_id,
                submission_id,
                idempotency_key or None,
                technical_state,
                RULESET_VERSION,
                started_at,
            ),
        )
        self.connection.commit()
        return run_id

    def find_run_by_idempotency_key(self, idempotency_key: str) -> Optional[dict[str, Any]]:
        if not idempotency_key:
            return None
        row = self.connection.execute(
            """
            SELECT * FROM processing_runs
            WHERE idempotency_key = ?
            ORDER BY started_at ASC
            LIMIT 1
            """,
            (idempotency_key,),
        ).fetchone()
        return _row_to_dict(row)

    def update_run(
        self,
        run_id: str,
        *,
        technical_state: Optional[str] = None,
        business_status: Optional[str] = None,
        primary_reason: Optional[str] = None,
        next_action: Optional[str] = None,
        completed_at: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        updates: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("technical_state", technical_state),
            ("business_status", business_status),
            ("primary_reason", primary_reason),
            ("next_action", next_action),
            ("completed_at", completed_at),
            ("duration_ms", duration_ms),
        ):
            if value is not None:
                updates.append(f"{column} = ?")
                values.append(value)
        if not updates:
            return
        values.append(run_id)
        self.connection.execute(
            f"UPDATE processing_runs SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        self.connection.commit()

    @staticmethod
    def _safe_extracted_fields(fields: Mapping[str, str]) -> dict[str, str]:
        safe: dict[str, str] = {}
        for key, value in fields.items():
            normalized_key = re.sub(r"[^a-z0-9]", "_", key.lower()).strip("_")
            if normalized_key in {"account_number", "bank_account"}:
                safe[key] = mask_bank_account(str(value))
            else:
                safe[key] = str(value)
        return safe

    def save_documents(self, run_id: str, documents: Sequence[Any]) -> None:
        rows = []
        for document in documents:
            if hasattr(document, "fields"):
                fields = {
                    key: field.raw_value
                    for key, field in document.fields.items()
                }
                document_type = document.document_type
                filename = document.source_filename
                digest = document.sha256
                if not document.accepted:
                    extraction_status = "REJECTED"
                elif not document.readable:
                    extraction_status = "UNREADABLE"
                elif document.errors:
                    extraction_status = "PARTIAL"
                else:
                    extraction_status = "EXTRACTED"
            else:
                fields = dict(document.extracted_fields)
                document_type = document.document_type
                filename = document.source_document
                digest = None
                extraction_status = (
                    "UNREADABLE" if not document.machine_readable else "EXTRACTED"
                )
            rows.append(
                (
                    new_id(),
                    run_id,
                    document_type,
                    filename,
                    digest,
                    extraction_status,
                    json.dumps(self._safe_extracted_fields(fields), sort_keys=True),
                )
            )
        self.connection.executemany(
            """
            INSERT INTO documents (
                id, run_id, document_type, sanitized_filename,
                sha256_hash, extraction_status, extracted_fields_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.connection.commit()

    def save_rule_results(
        self,
        run_id: str,
        results: Sequence[ValidationResult],
    ) -> None:
        rows = []
        for result in results:
            submitted_value = result.submitted_value
            if (
                result.rule_code in {"DUPLICATE_BANK", "BLOCKLIST_BANK_ACCOUNT"}
                or "BANK_ACCOUNT" in result.rule_code
            ):
                submitted_value = mask_bank_account(submitted_value)
            rows.append(
                (
                    new_id(),
                    run_id,
                    result.rule_code,
                    result.category,
                    int(result.passed),
                    result.severity,
                    result.message,
                    submitted_value,
                    result.reference_value,
                    result.source_document,
                    result.next_action,
                    result.rule_version,
                )
            )
        self.connection.executemany(
            """
            INSERT INTO rule_results (
                id, run_id, rule_code, category, passed, severity,
                message, submitted_value, reference_value,
                source_document, next_action, rule_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.connection.commit()

    def save_response(
        self,
        run_id: str,
        *,
        subject: str,
        body: str,
        review_status: str,
    ) -> str:
        communication_id = new_id()
        self.connection.execute(
            """
            INSERT INTO communications (
                id, run_id, subject, body, review_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (communication_id, run_id, subject, body, review_status, utc_now()),
        )
        self.connection.commit()
        return communication_id

    def add_audit_event(
        self,
        run_id: str,
        *,
        stage: str,
        event_type: str,
        message: str,
        duration_ms: Optional[float] = None,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO audit_events (
                run_id, stage, event_type, message, duration_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, stage, event_type, message, duration_ms, utc_now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_vendor_references(
        self,
        *,
        exclude_submission_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if exclude_submission_id:
            rows = self.connection.execute(
                """
                SELECT id, vendor_name, normalized_vendor_name, tax_id,
                       bank_account_fingerprint
                FROM submissions
                WHERE id != ?
                ORDER BY created_at ASC
                """,
                (exclude_submission_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT id, vendor_name, normalized_vendor_name, tax_id,
                       bank_account_fingerprint
                FROM submissions
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_recent_submissions(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM submissions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_recent_runs(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT
                processing_runs.*,
                submissions.vendor_name
            FROM processing_runs
            JOIN submissions ON submissions.id = processing_runs.submission_id
            ORDER BY processing_runs.started_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]

    def filter_runs_by_business_status(self, status: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM processing_runs
            WHERE business_status = ?
            ORDER BY started_at DESC
            """,
            (status,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        return _row_to_dict(
            self.connection.execute(
                "SELECT * FROM processing_runs WHERE id = ?", (run_id,)
            ).fetchone()
        )

    def get_documents(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM documents
            WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["extracted_fields"] = json.loads(item.pop("extracted_fields_json"))
            result.append(item)
        return result

    def get_rule_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM rule_results
            WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_audit_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM audit_events
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_response(self, run_id: str) -> Optional[dict[str, Any]]:
        return _row_to_dict(
            self.connection.execute(
                """
                SELECT * FROM communications
                WHERE run_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        )

    def get_complete_run_detail(self, run_id: str) -> Optional[dict[str, Any]]:
        run = self.get_run(run_id)
        if run is None:
            return None
        submission = _row_to_dict(
            self.connection.execute(
                "SELECT * FROM submissions WHERE id = ?",
                (run["submission_id"],),
            ).fetchone()
        )
        return {
            "run": run,
            "submission": submission,
            "documents": self.get_documents(run_id),
            "rule_results": self.get_rule_results(run_id),
            "audit_events": self.get_audit_events(run_id),
            "response": self.get_response(run_id),
        }

    def count_runs_by_status(self) -> dict[str, int]:
        rows = self.connection.execute(
            """
            SELECT business_status, COUNT(*) AS count
            FROM processing_runs
            WHERE business_status IS NOT NULL
            GROUP BY business_status
            """
        ).fetchall()
        counts = {"APPROVED": 0, "PENDING": 0, "REJECTED": 0}
        counts.update({row["business_status"]: int(row["count"]) for row in rows})
        return counts

    # Short aliases for dashboard callers.
    get_run_detail = get_complete_run_detail
    retrieve_documents = get_documents
    retrieve_rule_results = get_rule_results
    retrieve_audit_events = get_audit_events
    retrieve_response = get_response