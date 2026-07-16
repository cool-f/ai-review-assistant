"""Pure learning-progress rules.

The module interface is intentionally small: callers submit an observable answer
or change the optional manual override. Persistence details stay outside this seam.
"""

from dataclasses import dataclass, replace


ProgressStatus = str
VALID_STATUSES = frozenset(
    {"not_started", "in_progress", "mastered", "struggling"}
)


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    status: ProgressStatus
    manual_status: ProgressStatus | None
    correct_count: int
    total_count: int
    correct_streak: int
    answered_question_ids: tuple[str, ...]

    @classmethod
    def empty(cls) -> "ProgressSnapshot":
        return cls(
            status="not_started",
            manual_status=None,
            correct_count=0,
            total_count=0,
            correct_streak=0,
            answered_question_ids=(),
        )


def record_answer(
    progress: ProgressSnapshot,
    *,
    question_id: str,
    correct: bool,
) -> ProgressSnapshot:
    """Return the progress after the first counted answer to a question."""
    if question_id in progress.answered_question_ids:
        return progress

    total_count = progress.total_count + 1
    correct_count = progress.correct_count + (1 if correct else 0)
    correct_streak = progress.correct_streak + 1 if correct else 0

    if progress.manual_status is not None:
        status = progress.manual_status
    elif not correct:
        status = "struggling"
    elif correct_streak >= 3:
        status = "mastered"
    else:
        status = "in_progress"

    return replace(
        progress,
        status=status,
        correct_count=correct_count,
        total_count=total_count,
        correct_streak=correct_streak,
        answered_question_ids=progress.answered_question_ids + (question_id,),
    )


def set_manual_status(
    progress: ProgressSnapshot,
    status: ProgressStatus | None,
) -> ProgressSnapshot:
    """Set a manual override, or clear it and resume automatic evaluation."""
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"invalid progress status: {status}")

    if status is not None:
        return replace(progress, status=status, manual_status=status)

    if progress.total_count == 0:
        automatic_status = "not_started"
    elif progress.correct_streak >= 3:
        automatic_status = "mastered"
    elif progress.correct_streak == 0:
        automatic_status = "struggling"
    else:
        automatic_status = "in_progress"

    return replace(progress, status=automatic_status, manual_status=None)
