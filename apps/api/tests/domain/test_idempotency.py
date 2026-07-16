from review_assistant.domain.idempotency import resolve_chat_request


def test_completed_chat_request_is_replayed_without_new_ai_call() -> None:
    assert resolve_chat_request("completed") == "replay"


def test_failed_chat_request_retries_without_duplicate_user_message() -> None:
    assert resolve_chat_request("failed") == "retry"


def test_same_key_with_different_content_is_a_conflict() -> None:
    assert resolve_chat_request("completed", content_matches=False) == "conflict"
