from review_assistant.domain.budget import BudgetState


def test_budget_blocks_new_ai_calls_at_the_limit() -> None:
    assert BudgetState(used=100, limit=100).allows_ai_call is False


def test_zero_budget_means_unlimited() -> None:
    assert BudgetState(used=999, limit=0).allows_ai_call is True
