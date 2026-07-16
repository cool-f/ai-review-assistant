from review_assistant.domain.study_progress import (
    ProgressSnapshot,
    record_answer,
    set_manual_status,
)


def test_first_correct_answer_starts_progress_immediately() -> None:
    progress = ProgressSnapshot.empty()

    updated = record_answer(progress, question_id="question-1", correct=True)

    assert updated.status == "in_progress"
    assert updated.total_count == 1
    assert updated.correct_count == 1
    assert updated.correct_streak == 1


def test_manual_override_can_return_to_automatic_progress() -> None:
    overridden = set_manual_status(ProgressSnapshot.empty(), "mastered")
    automatic = set_manual_status(overridden, None)

    updated = record_answer(automatic, question_id="question-1", correct=False)

    assert updated.manual_status is None
    assert updated.status == "struggling"


def test_latest_wrong_answer_resets_streak_and_marks_struggling() -> None:
    progress = ProgressSnapshot.empty()
    for number in range(1, 3):
        progress = record_answer(progress, question_id=f"q-{number}", correct=True)

    updated = record_answer(progress, question_id="q-3", correct=False)

    assert updated.correct_streak == 0
    assert updated.status == "struggling"


def test_three_consecutive_correct_answers_are_mastered_and_duplicates_do_not_count() -> None:
    progress = ProgressSnapshot.empty()
    for number in range(1, 4):
        progress = record_answer(progress, question_id=f"q-{number}", correct=True)

    duplicate = record_answer(progress, question_id="q-3", correct=False)

    assert progress.status == "mastered"
    assert duplicate == progress
