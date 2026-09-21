# VendorSure — Phase 1

VendorSure Phase 1 is a deterministic vendor-onboarding business-logic layer.
It evaluates synthetic vendor submissions using explicit Python rules and
returns `APPROVED`, `PENDING`, or `REJECTED` with rule-level evidence.

This phase intentionally does **not** include Streamlit, PDF extraction,
SQLite, deployment configuration, network calls, AI, LLMs, machine learning,
or model APIs.

## Scope

The rules cover:

- Required submission fields
- GSTIN, IFSC and email structure
- Legal-name and GSTIN consistency with a tax certificate
- Bank-account holder matching the legal name or explicitly declared trade name
- Compliance declaration signer and date
- Duplicate tax IDs and bank accounts
- Synthetic tax-ID and bank-account blocklists

Format and ordinary consistency failures are `PENDING`. Duplicate and
synthetic-blocklist risks are `REJECTED`. Decision precedence is:

```text
Any REJECTED rule → REJECTED
Otherwise, any PENDING rule → PENDING
Otherwise → APPROVED
```

Name comparisons are exact after deterministic normalization. Normalization
lowercases values, removes punctuation, collapses whitespace, and removes
trailing Indian legal suffixes such as `Pvt Ltd`, `Private Limited`, `Ltd`,
`Limited`, and `LLP`. Original submitted values remain unchanged in the typed
models and validation evidence.

## Run the tests

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

## Evaluate the synthetic scenarios

```python
from vendorsure.decisions import evaluate_submission
from vendorsure.demo_data import get_demo_scenarios

for scenario in get_demo_scenarios():
    decision = evaluate_submission(
        scenario.submission,
        existing_submissions=scenario.existing_submissions,
        blocklisted_tax_ids=scenario.blocklisted_tax_ids,
        blocklisted_bank_accounts=scenario.blocklisted_bank_accounts,
    )
    print(scenario.name, decision.status)
```

The prepared scenarios calculate as follows:

- Apex Components Private Limited → `APPROVED`
- Nova Industrial Services Private Limited → `PENDING` because of `BANK_NAME_MATCH`
- Orion Trading Company → `REJECTED` because of `DUPLICATE_BANK`
- BluePeak Logistics → `PENDING` because of `DOC_REQUIRED`

Those outcomes are calculated by the shared rules engine; they are not stored
on the scenarios.