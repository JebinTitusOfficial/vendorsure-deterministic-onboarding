"""VendorSure Streamlit application."""

from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import streamlit as st

from vendorsure.demo_data import DemoScenario, get_demo_scenarios
from vendorsure.extraction import (
    BANK_PROOF,
    COMPLIANCE_DECLARATION,
    MAX_FILE_SIZE,
    TAX_CERTIFICATE,
)
from vendorsure.models import VendorSubmission
from vendorsure.repository import Repository
from vendorsure.workflow import (
    ProgressEvent,
    WORKFLOW_STAGES,
    WorkflowResult,
    WorkflowService,
)


APP_TITLE = "VendorSure"
DISCLAIMER = (
    "Synthetic demonstration data — not a real tax, banking or compliance "
    "verification service."
)
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"
DEFAULT_DATABASE_PATH = Path(
    os.environ.get("VENDORSURE_DB_PATH", "data/vendorsure.db")
)

STATUS_COLORS = {
    "APPROVED": "#15803d",
    "PENDING": "#b45309",
    "REJECTED": "#b91c1c",
    "COMPLETED": "#1d4ed8",
    "FAILED": "#6b7280",
}

RULE_CATALOG = [
    ("REQUIRED_FIELDS", "FORMAT", "Required form fields are present.", "PENDING", "Request the missing field."),
    ("DOC_REQUIRED", "DOCUMENT", "The required tax certificate is present.", "PENDING", "Upload the missing document."),
    ("DOC_READABLE", "DOCUMENT", "The uploaded PDF contains machine-readable text.", "PENDING", "Upload a readable PDF or route it for manual review."),
    ("GSTIN_FORMAT", "FORMAT", "GSTIN has the expected 15-character structure.", "PENDING", "Correct the GSTIN format."),
    ("IFSC_FORMAT", "FORMAT", "IFSC has the expected 11-character structure.", "PENDING", "Correct the IFSC format."),
    ("EMAIL_FORMAT", "FORMAT", "Email has a valid basic structure.", "PENDING", "Correct the email address."),
    ("LEGAL_NAME_MATCH", "CONSISTENCY", "Submitted legal name matches the tax certificate.", "PENDING", "Review the legal name and tax certificate."),
    ("GSTIN_MATCH", "CONSISTENCY", "Submitted GSTIN matches the tax certificate.", "PENDING", "Review the GSTIN and tax certificate."),
    ("BANK_NAME_MATCH", "CONSISTENCY", "Bank holder matches the legal or declared trade name.", "PENDING", "Confirm the bank holder or declare the trade name."),
    ("COMPLIANCE_SIGNER", "CONSISTENCY", "Compliance signer is present and consistent.", "PENDING", "Review the compliance declaration signer."),
    ("COMPLIANCE_DATE", "CONSISTENCY", "Compliance declaration date is valid and consistent.", "PENDING", "Provide a matching declaration date."),
    ("DUPLICATE_TAX_ID", "RISK", "Tax ID is not associated with another vendor identity.", "REJECTED", "Escalate for manual compliance review."),
    ("DUPLICATE_BANK", "RISK", "Bank account is not associated with an unrelated vendor.", "REJECTED", "Escalate for manual fraud review."),
    ("BLOCKLIST_TAX_ID", "RISK", "Tax ID is not on the synthetic blocklist.", "REJECTED", "Escalate for manual compliance review."),
    ("BLOCKLIST_BANK_ACCOUNT", "RISK", "Bank account is not on the synthetic blocklist.", "REJECTED", "Escalate for manual compliance review."),
]

QUEUE_FILTERS = ("All action required", "Pending", "Rejected", "Technical failures")
QUEUE_COLUMNS = (
    "Vendor",
    "Business status",
    "Primary reason",
    "Next action",
    "Submitted",
    "Open",
)
HISTORY_COLUMNS = (
    "Vendor",
    "Run ID",
    "Submitted",
    "Technical state",
    "Business status",
    "Duration",
    "Open",
)


def status_badge(status: str | None) -> str:
    """Return consistent status markup for the UI and smoke tests."""

    label = status or "—"
    color = STATUS_COLORS.get(label, "#6b7280")
    return (
        f"<span class='status-badge' style='background:{color};'>"
        f"{label}</span>"
    )


def _scenario_by_label(label: str) -> DemoScenario | None:
    return next((scenario for scenario in get_demo_scenarios() if scenario.name == label), None)


def scenario_form_data(scenario: DemoScenario | None) -> dict[str, str]:
    """Map a prepared domain scenario into editable form fields."""

    if scenario is None:
        return {
            "vendor_id": "",
            "legal_name": "",
            "trade_name": "",
            "entity_type": "Private Limited",
            "country": "India",
            "gstin": "",
            "registered_address": "",
            "contact_name": "",
            "email": "",
            "bank_holder": "",
            "bank_account": "",
            "ifsc": "",
            "bank_name": "",
            "compliance_signer": "Authorized Signatory",
            "compliance_date": date.today().isoformat(),
        }

    addresses = {
        "Apex Components Private Limited": "12 Synthetic Industrial Estate, Pune",
        "Nova Industrial Services Private Limited": "28 Synthetic Works, Bengaluru",
        "Orion Trading Company": "7 Synthetic Market Road, Ahmedabad",
        "BluePeak Logistics": "44 Synthetic Logistics Park, Mumbai",
    }
    bank_names = {
        "Apex Components Private Limited": "Synthetic HDFC Bank",
        "Nova Industrial Services Private Limited": "Synthetic ICICI Bank",
        "Orion Trading Company": "Synthetic Axis Bank",
        "BluePeak Logistics": "Synthetic Yes Bank",
    }
    submission = scenario.submission
    return {
        "vendor_id": submission.vendor_id,
        "legal_name": submission.legal_name,
        "trade_name": submission.declared_trade_name or "",
        "entity_type": "Private Limited",
        "country": "India",
        "gstin": submission.gstin,
        "registered_address": addresses.get(scenario.name, ""),
        "contact_name": "Authorized Signatory",
        "email": submission.email,
        "bank_holder": submission.bank_account_holder,
        "bank_account": submission.bank_account,
        "ifsc": submission.ifsc,
        "bank_name": bank_names.get(scenario.name, ""),
        "compliance_signer": submission.compliance_signer or "Authorized Signatory",
        "compliance_date": submission.compliance_date or date.today().isoformat(),
    }


def validate_form_data(data: Mapping[str, Any]) -> dict[str, str]:
    """Validate only essential user inputs before invoking the workflow."""

    fields = {
        "legal_name": "Legal company name",
        "gstin": "GSTIN",
        "email": "Contact email",
        "bank_holder": "Account holder",
        "bank_account": "Account number",
        "ifsc": "IFSC",
    }
    errors = {}
    for field, label in fields.items():
        if not str(data.get(field, "")).strip():
            errors[field] = f"{label} is required."
    email = str(data.get("email", "")).strip()
    if email and ("@" not in email or "." not in email.rsplit("@", 1)[-1]):
        errors["email"] = "Enter a valid contact email."
    return errors


def filter_runs(
    runs: list[Mapping[str, Any]],
    *,
    queue: bool,
    status_filter: str,
    search: str = "",
) -> list[Mapping[str, Any]]:
    """Apply the UI-only queue or history view filters."""

    if queue:
        visible = [
            run
            for run in runs
            if run["business_status"] in {"PENDING", "REJECTED"}
            or run["technical_state"] == "FAILED"
        ]
        if status_filter == "Pending":
            visible = [run for run in visible if run["business_status"] == "PENDING"]
        elif status_filter == "Rejected":
            visible = [run for run in visible if run["business_status"] == "REJECTED"]
        elif status_filter == "Technical failures":
            visible = [run for run in visible if run["technical_state"] == "FAILED"]
    else:
        visible = list(runs)
        if status_filter != "All":
            visible = [
                run
                for run in visible
                if (
                    run["technical_state"]
                    if status_filter == "FAILED"
                    else run["business_status"]
                )
                == status_filter
            ]
    normalized_search = search.strip().lower()
    if normalized_search:
        visible = [
            run for run in visible if normalized_search in run["vendor_name"].lower()
        ]
    return visible


def build_submission(form_data: Mapping[str, Any]) -> VendorSubmission:
    """Build the backend submission without embedding any business outcome."""

    return VendorSubmission(
        vendor_id=str(form_data.get("vendor_id") or f"ui-{uuid.uuid4()}"),
        legal_name=str(form_data.get("legal_name", "")),
        gstin=str(form_data.get("gstin", "")),
        email=str(form_data.get("email", "")),
        ifsc=str(form_data.get("ifsc", "")),
        bank_account=str(form_data.get("bank_account", "")),
        bank_account_holder=str(form_data.get("bank_holder", "")),
        declared_trade_name=str(form_data.get("trade_name", "")).strip() or None,
        compliance_signer=str(form_data.get("compliance_signer", "")).strip() or None,
        compliance_date=str(form_data.get("compliance_date", "")).strip() or None,
    )


def _fixture_document_map(scenario_name: str) -> dict[str, tuple[str, bytes]]:
    prefix = {
        "Apex Components Private Limited": "apex",
        "Nova Industrial Services Private Limited": "nova",
        "Orion Trading Company": "orion",
        "BluePeak Logistics": "bluepeak",
    }[scenario_name]
    documents = {
        BANK_PROOF: (
            f"{prefix}_bank_proof.pdf",
            (FIXTURE_DIR / f"{prefix}_bank_proof.pdf").read_bytes(),
        ),
        COMPLIANCE_DECLARATION: (
            f"{prefix}_compliance_declaration.pdf",
            (FIXTURE_DIR / f"{prefix}_compliance_declaration.pdf").read_bytes(),
        ),
    }
    if scenario_name != "BluePeak Logistics":
        documents[TAX_CERTIFICATE] = (
            f"{prefix}_tax_certificate.pdf",
            (FIXTURE_DIR / f"{prefix}_tax_certificate.pdf").read_bytes(),
        )
    return documents


def load_demo_history(repository: Repository) -> list[WorkflowResult]:
    """Run each prepared scenario through the real workflow exactly once per key."""

    service = WorkflowService(repository)
    results = []
    for scenario in get_demo_scenarios():
        results.append(
            service.run(
                scenario.submission,
                _fixture_document_map(scenario.name),
                idempotency_key=f"demo-history-{scenario.submission.vendor_id}",
                existing_submissions=scenario.existing_submissions,
            )
        )
    return results


def _apply_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --navy:#0b1f3a;
            --navy-soft:#12345b;
            --blue:#2563eb;
            --blue-soft:#eff6ff;
            --surface:#ffffff;
            --canvas:#f4f7fb;
            --line:#d9e2ec;
            --muted:#64748b;
            --text:#0f172a;
        }
        .stApp {
            background:
                radial-gradient(circle at 92% 2%, rgba(37,99,235,.07), transparent 22rem),
                var(--canvas);
            color:var(--text);
        }
        [data-testid="stMainBlockContainer"] {
            max-width:1480px;
            padding-top:2.25rem;
            padding-bottom:4rem;
        }
        [data-testid="stSidebar"] {
            background:linear-gradient(180deg, var(--navy) 0%, #07172c 100%);
            border-right:1px solid rgba(255,255,255,.08);
        }
        [data-testid="stSidebar"] * { color:#f8fafc !important; }
        [data-testid="stSidebar"] [role="radiogroup"] label {
            border:1px solid transparent;
            border-radius:9px;
            padding:.42rem .55rem;
            margin:.08rem 0;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background:rgba(255,255,255,.07);
        }
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
            background:rgba(59,130,246,.20);
            border-color:rgba(147,197,253,.28);
        }
        header[data-testid="stHeader"] { background:rgba(244,247,251,.92); }
        div[data-testid="stDecoration"] { display:none; }
        h1, h2, h3 { color:var(--navy); letter-spacing:-.025em; }
        h1 { font-size:2.35rem !important; margin-bottom:.35rem !important; }
        .brand {
            color:white;
            font-size:1.45rem;
            font-weight:750;
            letter-spacing:-.02em;
            padding-top:.6rem;
        }
        .brand-mark {
            align-items:center;
            background:#2563eb;
            border-radius:8px;
            display:inline-flex;
            font-size:.9rem;
            height:28px;
            justify-content:center;
            margin-right:.5rem;
            width:28px;
        }
        .eyebrow {
            color:#41658f;
            font-size:.74rem;
            font-weight:750;
            letter-spacing:.13em;
            margin-bottom:.2rem;
            text-transform:uppercase;
        }
        .page-intro {
            color:var(--muted);
            font-size:.96rem;
            margin:-.15rem 0 1.25rem;
            max-width:760px;
        }
        .status-badge {
            box-shadow:0 1px 2px rgba(15,23,42,.12);
            color:white;
            display:inline-block;
            border-radius:999px;
            font-size:.7rem;
            font-weight:750;
            letter-spacing:.025em;
            padding:.3rem .65rem;
        }
        .notice {
            background:#fff8e7;
            border:1px solid #efd28e;
            border-radius:10px;
            color:#704b0c;
            margin:.25rem 0 1.1rem;
            padding:.75rem 1rem;
        }
        .metric-card {
            background:var(--surface);
            border:1px solid var(--line);
            border-radius:12px;
            box-shadow:0 4px 16px rgba(15,23,42,.045);
            min-height:98px;
            padding:1rem;
            position:relative;
            overflow:hidden;
        }
        .metric-card::before {
            background:var(--accent, var(--blue));
            content:"";
            height:3px;
            left:0;
            position:absolute;
            right:0;
            top:0;
        }
        .metric-blue { --accent:#2563eb; }
        .metric-green { --accent:#16a34a; }
        .metric-amber { --accent:#d97706; }
        .metric-red { --accent:#dc2626; }
        .metric-violet { --accent:#7c3aed; }
        .metric-label { color:var(--muted); font-size:.78rem; }
        .metric-value { color:var(--navy); font-size:1.65rem; font-weight:750; margin-top:.32rem; }
        .summary-card {
            background:var(--surface);
            border:1px solid var(--line);
            border-radius:12px;
            box-shadow:0 3px 12px rgba(15,23,42,.04);
            min-height:105px;
            padding:.9rem 1rem;
        }
        .summary-label { color:var(--muted); font-size:.72rem; font-weight:650; text-transform:uppercase; }
        .summary-value { color:var(--navy); font-size:.94rem; font-weight:650; margin-top:.5rem; overflow-wrap:anywhere; }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background:rgba(255,255,255,.78);
            border-color:var(--line) !important;
            border-radius:12px !important;
            box-shadow:0 3px 12px rgba(15,23,42,.035);
        }
        div[data-testid="stExpander"] {
            background:rgba(255,255,255,.78);
            border-color:var(--line) !important;
            border-radius:10px !important;
        }
        div[data-testid="stMetric"] { background:white; border:1px solid var(--line); border-radius:10px; padding:.65rem; }
        section[data-testid="stMain"] label,
        section[data-testid="stMain"] [data-testid="stWidgetLabel"],
        section[data-testid="stMain"] [data-testid="stWidgetLabel"] p {
            color:#334155 !important;
        }
        section[data-testid="stMain"] input,
        section[data-testid="stMain"] textarea {
            background:#ffffff !important;
            color:#0f172a !important;
            border-color:#cbd5e1 !important;
        }
        section[data-testid="stMain"] input::placeholder,
        section[data-testid="stMain"] textarea::placeholder {
            color:#64748b !important;
            opacity:1 !important;
        }
        section[data-testid="stMain"] div[data-baseweb="input"],
        section[data-testid="stMain"] div[data-baseweb="textarea"],
        section[data-testid="stMain"] div[data-baseweb="select"] > div {
            background:#ffffff !important;
            border-color:#cbd5e1 !important;
            color:#0f172a !important;
        }
        section[data-testid="stMain"] div[data-baseweb="select"] * {
            color:#0f172a !important;
        }
        section[data-testid="stMain"] section[data-testid="stFileUploaderDropzone"] {
            background:#ffffff !important;
            border:1px dashed #cbd5e1 !important;
        }
        section[data-testid="stMain"] section[data-testid="stFileUploaderDropzone"] * {
            color:#334155 !important;
        }
        section[data-testid="stMain"] div.stButton > button {
            background:#ffffff !important;
            color:#0f172a !important;
            border:1px solid #94a3b8 !important;
            border-radius:8px !important;
            font-weight:650 !important;
        }
        section[data-testid="stMain"] div.stButton > button:hover {
            background:#eff6ff !important;
            color:#0f172a !important;
            border-color:#2563eb !important;
        }
        section[data-testid="stMain"] div.stButton > button[kind="primary"] {
            background:#1d4ed8 !important;
            color:#ffffff !important;
            border-color:#1d4ed8 !important;
            box-shadow:0 4px 12px rgba(37,99,235,.20);
        }
        section[data-testid="stMain"] div.stButton > button[kind="primary"]:hover {
            background:#1e40af !important;
            color:#ffffff !important;
            border-color:#1e40af !important;
        }
        section[data-testid="stMain"] pre,
        section[data-testid="stMain"] div[data-testid="stCode"] {
            background:#0f172a !important;
            color:#e2e8f0 !important;
        }
        section[data-testid="stMain"] div[data-testid="stJson"] {
            background:#0f172a !important;
            color:#e2e8f0 !important;
            border-radius:6px;
            padding:.35rem;
        }
        section[data-testid="stMain"] hr { border-color:var(--line); }
        @media (max-width: 900px) {
            [data-testid="stMainBlockContainer"] { padding-left:1rem; padding-right:1rem; }
            h1 { font-size:1.9rem !important; }
            .metric-card { min-height:88px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _repository() -> Repository | None:
    if "repository_error" in st.session_state:
        st.error(st.session_state["repository_error"])
        return None
    if "repository" not in st.session_state:
        try:
            DEFAULT_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
            st.session_state["repository"] = Repository(DEFAULT_DATABASE_PATH)
        except Exception as error:
            st.session_state["repository_error"] = (
                "VendorSure could not open its local SQLite database. "
                f"Recoverable error: {type(error).__name__}."
            )
            st.error(st.session_state["repository_error"])
            return None
    return st.session_state["repository"]


def _render_metrics(repository: Repository) -> None:
    counts = repository.count_runs_by_status()
    runs = repository.list_recent_runs(1000)
    completed = [run for run in runs if run["technical_state"] == "COMPLETED"]
    human_action = counts["PENDING"] + counts["REJECTED"]
    human_percent = (human_action / len(completed) * 100) if completed else 0
    columns = st.columns(5)
    values = [
        ("Completed runs", len(completed), "metric-blue"),
        ("Approved", counts["APPROVED"], "metric-green"),
        ("Pending", counts["PENDING"], "metric-amber"),
        ("Rejected", counts["REJECTED"], "metric-red"),
        ("Human action", f"{human_percent:.0f}%", "metric-violet"),
    ]
    for column, (label, value, tone) in zip(columns, values):
        with column:
            st.markdown(
                f"<div class='metric-card {tone}'><div class='metric-label'>{label}</div>"
                f"<div class='metric-value'>{value}</div></div>",
                unsafe_allow_html=True,
            )


def _render_runs(
    repository: Repository,
    *,
    title: str,
    queue: bool = False,
) -> None:
    st.subheader(title)
    filter_options = list(
        QUEUE_FILTERS
        if queue
        else ("All", "APPROVED", "PENDING", "REJECTED", "FAILED")
    )
    status_filter = st.selectbox(
        "Status filter",
        filter_options,
        key=f"{title}-status-filter",
    )
    search = st.text_input("Search by vendor name", key=f"{title}-search").strip().lower()
    runs = filter_runs(
        repository.list_recent_runs(1000),
        queue=queue,
        status_filter=status_filter,
        search=search,
    )
    if not runs:
        st.info("No runs match the selected filters.")
        return
    column_labels = QUEUE_COLUMNS if queue else HISTORY_COLUMNS
    widths = (
        [2, 1.3, 2.2, 2.6, 1.5, 0.8]
        if queue
        else [2, 1.5, 1.4, 1.1, 1.25, 1.2, 0.8]
    )
    header = st.columns(widths)
    for column, label in zip(header, column_labels):
        column.caption(label)

    def open_run(run_id: str) -> None:
        st.session_state["selected_run_id"] = run_id
        st.session_state["page"] = "Run History"

    for run in runs:
        with st.container(border=True):
            columns = st.columns(widths, vertical_alignment="center")
            columns[0].markdown(f"**{run['vendor_name']}**")
            if queue:
                columns[1].markdown(
                    status_badge(run["business_status"] or "FAILED"),
                    unsafe_allow_html=True,
                )
                columns[2].write(run["primary_reason"] or "Technical workflow failure")
                columns[3].write(
                    run["next_action"] or "Correct the technical input and retry."
                )
                columns[4].caption(run["started_at"].replace("T", " ")[:19])
                open_column = columns[5]
            else:
                columns[1].code(run["id"][:8])
                columns[2].caption(run["started_at"].replace("T", " ")[:19])
                columns[3].markdown(
                    status_badge(run["technical_state"]),
                    unsafe_allow_html=True,
                )
                columns[4].markdown(
                    status_badge(run["business_status"]),
                    unsafe_allow_html=True,
                )
                duration = (
                    f"{run['duration_ms']:.2f} ms"
                    if run["duration_ms"] is not None
                    else "—"
                )
                columns[5].caption(duration)
                open_column = columns[6]
            open_column.button(
                "Open",
                key=f"open-{run['id']}",
                on_click=open_run,
                args=(run["id"],),
                use_container_width=True,
            )


def _render_run_detail(repository: Repository, run_id: str) -> None:
    detail = repository.get_complete_run_detail(run_id)
    if not detail:
        st.error("This workflow run could not be found.")
        return
    if st.button("← Back to runs"):
        st.session_state["selected_run_id"] = None
        st.rerun()
    run = detail["run"]
    submission = detail["submission"]
    st.markdown("<div class='eyebrow'>Run detail</div>", unsafe_allow_html=True)
    st.header(submission["vendor_name"])
    overview = st.columns(4)
    overview_values = [
        ("Run ID", run["id"]),
        ("Technical state", run["technical_state"]),
        ("Business status", run["business_status"] or "—"),
        ("Duration", f"{run['duration_ms'] or 0:.2f} ms"),
    ]
    for column, (label, value) in zip(overview, overview_values):
        column.markdown(
            f"<div class='summary-card'><div class='summary-label'>{label}</div>"
            f"<div class='summary-value'>{value}</div></div>",
            unsafe_allow_html=True,
        )
    st.caption(
        f"Submitted {run['started_at']} · Ruleset {run['ruleset_version']} · "
        f"Primary reason: {run['primary_reason'] or '—'}"
    )

    with st.expander("Documents", expanded=True):
        for document in detail["documents"]:
            st.markdown(
                f"**{document['document_type']}** · `{document['sanitized_filename']}` · "
                f"{document['extraction_status']} · SHA-256 "
                f"`{(document['sha256_hash'] or '')[:12]}…`"
            )
            fields = document["extracted_fields"]
            if fields:
                st.json(fields)
            else:
                st.caption("No extracted fields.")

    with st.expander("Rule results", expanded=True):
        for result in detail["rule_results"]:
            state = "PASS" if result["passed"] else "FAIL"
            st.markdown(
                f"**{result['rule_code']}** · `{state}` · "
                f"{result['category']} · {result['severity'] or '—'}"
            )
            st.caption(result["message"])
            st.write(
                f"Submitted: `{result['submitted_value'] or '—'}` · "
                f"Reference: `{result['reference_value'] or '—'}` · "
                f"Source: `{result['source_document'] or '—'}`"
            )
            if result["next_action"]:
                st.caption(f"Next action: {result['next_action']}")

    with st.expander("Prepared response", expanded=True):
        response = detail["response"]
        if response:
            st.write(f"**Subject:** {response['subject']}")
            st.text_area("Copy-friendly message", response["body"], height=150, disabled=True)
            st.caption(f"Review status: {response['review_status']}")
        else:
            st.info("No business response was prepared because the workflow failed technically.")

    with st.expander("Audit timeline"):
        for event in detail["audit_events"]:
            duration = (
                f" · {event['duration_ms']:.3f} ms"
                if event["duration_ms"] is not None
                else ""
            )
            st.write(
                f"`{event['created_at']}` · **{event['stage']}** · "
                f"{event['event_type']}{duration} — {event['message']}"
            )


def render_review_queue(repository: Repository) -> None:
    st.markdown("<div class='eyebrow'>Procurement operations</div>", unsafe_allow_html=True)
    st.title("Review Queue")
    st.markdown(
        "<div class='page-intro'>Prioritized exceptions that need a procurement "
        "or compliance decision.</div>",
        unsafe_allow_html=True,
    )
    st.markdown(f"<div class='notice'>{DISCLAIMER}</div>", unsafe_allow_html=True)
    _render_metrics(repository)
    if not repository.list_recent_runs(1):
        st.info("No workflow runs exist yet.")
        if st.button("Load demonstration history", type="primary"):
            with st.spinner("Running four synthetic scenarios through VendorSure..."):
                load_demo_history(repository)
            st.rerun()
        return
    _render_runs(repository, title="Needs attention", queue=True)


def _render_stage_progress() -> dict[str, Any]:
    slots = {}
    for stage in WORKFLOW_STAGES:
        slots[stage] = st.empty()
        slots[stage].caption(f"○ {stage.replace('_', ' ').title()}")

    def callback(event: ProgressEvent) -> None:
        label = event.stage.replace("_", " ").title()
        if event.event_type == "STAGE_STARTED":
            slots[event.stage].info(f"⏳ {label} — running")
        elif event.event_type == "STAGE_COMPLETED":
            slots[event.stage].success(
                f"✓ {label} — {event.summary} ({event.duration_ms:.3f} ms)"
            )
        else:
            slots[event.stage].error(f"✕ {label} — {event.summary}")

    return {"slots": slots, "callback": callback}


def _render_result(result: WorkflowResult) -> None:
    if result.technical_state == "FAILED":
        st.error(
            f"Technical workflow failure at {result.stage_results[-1].stage if result.stage_results else 'unknown stage'}."
        )
        st.caption(result.error or "Recoverable error. Correct the input and retry.")
        return
    status = result.business_status
    if status == "APPROVED":
        st.success("APPROVED — Configured onboarding checks passed")
    elif status == "PENDING":
        st.warning(
            f"PENDING — Additional evidence or correction required\n\n"
            f"Primary reason: {result.primary_reason}\n\n"
            f"Next action: {result.next_action}"
        )
    else:
        st.error(
            f"REJECTED — Automatic onboarding stopped\n\n"
            f"Triggered control: {result.primary_reason}\n\n"
            f"Manual action: {result.next_action}"
        )
    if result.response:
        with st.expander("Prepared vendor response"):
            st.write(f"**{result.response.subject}**")
            st.text_area("Message", result.response.body, height=130, disabled=True)


def render_new_submission(repository: Repository) -> None:
    st.markdown("<div class='eyebrow'>Deterministic intake</div>", unsafe_allow_html=True)
    st.title("New Submission")
    st.markdown(
        "<div class='page-intro'>Submit vendor details and supporting evidence "
        "for a deterministic, explainable onboarding decision.</div>",
        unsafe_allow_html=True,
    )
    scenario_labels = ["Manual submission"] + [
        scenario.name for scenario in get_demo_scenarios()
    ]
    selected = st.selectbox("Load prepared scenario", scenario_labels, key="scenario_selector")
    previous = st.session_state.get("loaded_scenario")
    if previous != selected:
        st.session_state["loaded_scenario"] = selected
        st.session_state["form_data"] = scenario_form_data(
            _scenario_by_label(selected)
        )
        st.session_state.pop("workflow_result", None)
        st.rerun()

    form_data = st.session_state.setdefault("form_data", scenario_form_data(None))
    scenario = _scenario_by_label(selected)
    if scenario:
        prepared = _fixture_document_map(scenario.name)
        st.info(
            "Prepared PDFs selected internally: "
            + ", ".join(filename for filename, _ in prepared.values())
        )
    else:
        prepared = {}

    with st.form("new-submission-form"):
        with st.container(border=True):
            st.subheader("Company")
            st.caption("Registered identity used for tax-certificate comparison.")
            company = st.columns(2)
            form_data["legal_name"] = company[0].text_input(
                "Legal company name", value=form_data["legal_name"]
            )
            form_data["trade_name"] = company[1].text_input(
                "Trade name (optional)", value=form_data["trade_name"]
            )
            company2 = st.columns(3)
            form_data["entity_type"] = company2[0].selectbox(
                "Entity type",
                ["Private Limited", "Public Limited", "LLP", "Proprietorship", "Other"],
                index=["Private Limited", "Public Limited", "LLP", "Proprietorship", "Other"].index(
                    form_data["entity_type"]
                )
                if form_data["entity_type"] in ["Private Limited", "Public Limited", "LLP", "Proprietorship", "Other"]
                else 0,
            )
            company2[1].text_input("Country", value="India", disabled=True)
            form_data["gstin"] = company2[2].text_input("GSTIN", value=form_data["gstin"])
            form_data["registered_address"] = st.text_area(
                "Registered address", value=form_data["registered_address"]
            )

        with st.container(border=True):
            st.subheader("Contact")
            st.caption("Operational contact for clarification requests.")
            contact = st.columns(2)
            form_data["contact_name"] = contact[0].text_input(
                "Contact name", value=form_data["contact_name"]
            )
            form_data["email"] = contact[1].text_input(
                "Contact email", value=form_data["email"]
            )

        with st.container(border=True):
            st.subheader("Banking")
            st.caption("Account values are masked before persistence and display.")
            banking = st.columns(2)
            form_data["bank_holder"] = banking[0].text_input(
                "Account holder", value=form_data["bank_holder"]
            )
            form_data["bank_account"] = banking[1].text_input(
                "Account number", value=form_data["bank_account"], type="password"
            )
            banking2 = st.columns(2)
            form_data["ifsc"] = banking2[0].text_input("IFSC", value=form_data["ifsc"])
            form_data["bank_name"] = banking2[1].text_input(
                "Bank name", value=form_data["bank_name"]
            )

        with st.container(border=True):
            st.subheader("Documents")
            st.caption("Machine-readable PDFs only · maximum 5 MB per document.")
            uploads = {}
            if not scenario:
                upload_columns = st.columns(3)
                for column, document_type, label in zip(
                    upload_columns,
                    [TAX_CERTIFICATE, BANK_PROOF, COMPLIANCE_DECLARATION],
                    ["Tax Registration Certificate PDF", "Bank Proof PDF", "Compliance Declaration PDF"],
                ):
                    uploads[document_type] = column.file_uploader(
                        label, type=["pdf"], key=f"upload-{document_type}"
                    )
                    if uploads[document_type]:
                        size = uploads[document_type].size
                        column.caption(f"{uploads[document_type].name} · {size:,} bytes")
                        if size > MAX_FILE_SIZE:
                            column.error("Maximum file size is 5 MB.")
            else:
                st.info("The selected prepared PDFs will be processed by their explicit document types.")

        submitted = st.form_submit_button(
            "Run vendor verification",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        return
    errors = validate_form_data(form_data)
    if not scenario:
        for document_type, upload in uploads.items():
            if upload is not None and upload.size > MAX_FILE_SIZE:
                errors[document_type] = "PDF must be 5 MB or smaller."
    if errors:
        for error in errors.values():
            st.error(error)
        return

    if scenario:
        documents = prepared
        existing = scenario.existing_submissions
    else:
        documents = {
            document_type: upload
            for document_type, upload in uploads.items()
            if upload is not None
        }
        existing = ()
    submission = build_submission(form_data)
    progress = _render_stage_progress()
    action_key = str(uuid.uuid4())
    st.session_state["last_idempotency_key"] = action_key
    result = WorkflowService(repository).run(
        submission,
        documents,
        idempotency_key=action_key,
        existing_submissions=existing,
        progress_callback=progress["callback"],
    )
    st.session_state["workflow_result"] = result
    st.session_state["selected_run_id"] = result.run_id
    _render_result(result)


def render_run_history(repository: Repository) -> None:
    st.markdown("<div class='eyebrow'>Traceability</div>", unsafe_allow_html=True)
    st.title("Run History")
    selected_run_id = st.session_state.get("selected_run_id")
    if selected_run_id:
        _render_run_detail(repository, selected_run_id)
    else:
        st.markdown(
            "<div class='page-intro'>Complete immutable processing history for "
            "audit, traceability and evidence review.</div>",
            unsafe_allow_html=True,
        )
        _render_runs(repository, title="All workflow runs")


def render_validation_rules() -> None:
    st.markdown("<div class='eyebrow'>Controls</div>", unsafe_allow_html=True)
    st.title("Validation Rules")
    st.markdown(
        "<div class='page-intro'>A transparent, read-only controls catalog. "
        "Every outcome is produced by explicit rules—not an AI model.</div>",
        unsafe_allow_html=True,
    )
    st.caption("Format checks are not authoritative government or banking verification.")
    categories = ("FORMAT", "DOCUMENT", "CONSISTENCY", "RISK")
    tabs = st.tabs([category.title() for category in categories])
    for tab, category in zip(tabs, categories):
        with tab:
            for code, rule_category, check, severity, action in RULE_CATALOG:
                if rule_category != category:
                    continue
                with st.expander(f"{code} · {severity}"):
                    st.write(f"**What it checks:** {check}")
                    st.write(f"**Failure severity:** {severity}")
                    st.write(f"**Business impact:** {severity.title()} outcome if no higher-precedence result exists.")
                    st.write(f"**Required next action:** {action}")
    st.subheader("Decision precedence")
    st.markdown(
        "1. Any failed **REJECTED**-severity rule → **REJECTED**  \n"
        "2. Otherwise, any failed **PENDING**-severity rule → **PENDING**  \n"
        "3. Otherwise → **APPROVED**"
    )
    st.info(
        "Missing or ambiguous evidence produces Pending. Rejection is reserved "
        "for duplicate identifiers and synthetic blocklist controls."
    )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="✓", layout="wide")
    _apply_style()
    st.sidebar.markdown(
        "<div class='brand'><span class='brand-mark'>✓</span>VendorSure</div>",
        unsafe_allow_html=True,
    )
    st.sidebar.caption("Deterministic vendor onboarding")
    page = st.sidebar.radio(
        "Navigate",
        ["Review Queue", "New Submission", "Run History", "Validation Rules"],
        key="page",
    )
    repository = _repository()
    if repository is None:
        return
    if page == "Review Queue":
        render_review_queue(repository)
    elif page == "New Submission":
        render_new_submission(repository)
    elif page == "Run History":
        render_run_history(repository)
    else:
        render_validation_rules()


if __name__ == "__main__":
    main()
