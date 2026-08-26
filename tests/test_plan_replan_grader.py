from evals.product_baselines.test_plan_replan_001_obligation_revision import (
    _SCENARIOS,
    _plan_contract,
    _plan_counts,
)


def test_v7_plan_contract_separates_active_obligations_from_supersession_record():
    scenario = _SCENARIOS[0]
    plan = {
        "goal": "交付业务幂等、恢复后对账与验收条件",
        "steps": [
            {
                "step_id": "ordered-delivery",
                "description": "原候选已被后续结果契约取代",
                "status": "superseded",
            },
            {
                "step_id": "latest-result",
                "description": "交付业务幂等、恢复后对账与验收条件",
                "status": "completed",
            },
        ],
    }

    required, withdrawn_active, withdrawn_superseded = _plan_contract(
        plan,
        scenario,
    )

    assert all(required)
    assert not any(withdrawn_active)
    assert all(withdrawn_superseded)
    assert _plan_counts(plan) == (1, 0, 1)


def test_v7_plan_contract_rejects_withdrawn_content_marked_completed():
    scenario = _SCENARIOS[0]
    plan = {
        "goal": "交付业务幂等、恢复后对账与验收条件",
        "steps": [
            {
                "step_id": "ordered-delivery",
                "description": "完成依赖有序投递候选",
                "status": "completed",
            },
            {
                "step_id": "latest-result",
                "description": "交付业务幂等、恢复后对账与验收条件",
                "status": "completed",
            },
        ],
    }

    _, withdrawn_active, withdrawn_superseded = _plan_contract(plan, scenario)

    assert all(withdrawn_active)
    assert not any(withdrawn_superseded)


def test_v7_plan_counts_treats_superseded_as_terminal_without_completion():
    plan = {
        "steps": [
            {
                "step_id": "old-obligation",
                "description": "旧的阶段性义务",
                "status": "superseded",
            },
        ],
    }

    assert _plan_counts(plan) == (0, 0, 1)
