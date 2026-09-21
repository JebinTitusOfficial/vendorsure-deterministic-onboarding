from vendorsure.decisions import evaluate_submission
from vendorsure.demo_data import get_demo_scenarios


def evaluate_scenarios():
    return {
        scenario.name: evaluate_submission(
            scenario.submission,
            existing_submissions=scenario.existing_submissions,
            blocklisted_tax_ids=scenario.blocklisted_tax_ids,
            blocklisted_bank_accounts=scenario.blocklisted_bank_accounts,
        )
        for scenario in get_demo_scenarios()
    }


def test_all_four_scenarios_are_calculated_by_the_shared_engine():
    decisions = evaluate_scenarios()

    assert decisions["Apex Components Private Limited"].status == "APPROVED"

    nova = decisions["Nova Industrial Services Private Limited"]
    assert nova.status == "PENDING"
    assert any(
        result.rule_code == "BANK_NAME_MATCH" and not result.passed
        for result in nova.rule_results
    )

    orion = decisions["Orion Trading Company"]
    assert orion.status == "REJECTED"
    assert any(
        result.rule_code == "DUPLICATE_BANK"
        and not result.passed
        and result.severity == "REJECTED"
        for result in orion.rule_results
    )

    bluepeak = decisions["BluePeak Logistics"]
    assert bluepeak.status == "PENDING"
    assert any(
        result.rule_code == "DOC_REQUIRED" and not result.passed
        for result in bluepeak.rule_results
    )


def test_demo_scenarios_do_not_store_a_precomputed_status():
    for scenario in get_demo_scenarios():
        assert not hasattr(scenario, "status")
        assert not hasattr(scenario.submission, "status")