from typing import Literal


IdempotencyAction = Literal["start", "retry", "replay", "wait", "conflict"]


def resolve_chat_request(status: str | None, *, content_matches: bool = True) -> IdempotencyAction:
    if status is None:
        return "start"
    if not content_matches:
        return "conflict"
    return {"completed": "replay", "processing": "wait", "failed": "retry"}.get(status, "conflict")
