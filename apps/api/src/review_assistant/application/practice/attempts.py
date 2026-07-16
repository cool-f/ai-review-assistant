from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from review_assistant.application.practice.grading import GradingService
from review_assistant.domain.study_progress import ProgressSnapshot, record_answer
from review_assistant.infrastructure.persistence.models import (
    Courseware,
    GeneratedQuestion,
    KnowledgePoint,
    PracticeAttempt,
    StudyProgress,
)
from review_assistant.infrastructure.usage.context import usage_scope


class QuestionNotFoundError(ValueError):
    pass


class PracticeAttemptService:
    def __init__(self, db: AsyncSession, grader: GradingService | None = None):
        self.db = db
        self.grader = grader or GradingService()

    async def submit(self, *, course_id: str, question_id: str, answer: str) -> dict:
        result = await self.db.execute(
            select(GeneratedQuestion)
            .join(Courseware, Courseware.id == GeneratedQuestion.courseware_id)
            .where(GeneratedQuestion.id == question_id, Courseware.course_id == course_id)
        )
        question = result.scalar_one_or_none()
        if question is None:
            raise QuestionNotFoundError("题目不存在")

        with usage_scope("practice_grading", course_id=course_id):
            grade = await self.grader.grade(
                question_type=question.question_type,
                question=question.question_text,
                submitted=answer,
                expected=question.answer_text,
            )
        # Serialize progress updates per knowledge point so concurrent submissions
        # cannot both claim to be the first counted attempt.
        await self.db.execute(
            select(KnowledgePoint.id)
            .where(KnowledgePoint.id == question.knowledge_point_id)
            .with_for_update()
        )
        prior_count = await self.db.scalar(
            select(func.count(PracticeAttempt.id)).where(PracticeAttempt.question_id == question_id)
        ) or 0
        counted = prior_count == 0

        progress_result = await self.db.execute(
            select(StudyProgress)
            .where(StudyProgress.knowledge_point_id == question.knowledge_point_id)
            .with_for_update()
        )
        progress = progress_result.scalar_one_or_none()
        if progress is None:
            progress = StudyProgress(knowledge_point_id=question.knowledge_point_id)
            self.db.add(progress)

        if counted:
            snapshot = ProgressSnapshot(
                status=progress.status,
                manual_status=progress.manual_status,
                correct_count=progress.quiz_correct_count,
                total_count=progress.quiz_total_count,
                correct_streak=progress.correct_streak,
                answered_question_ids=tuple(progress.answered_question_ids or []),
            )
            updated = record_answer(snapshot, question_id=question_id, correct=grade.correct)
            progress.status = updated.status
            progress.manual_status = updated.manual_status
            progress.quiz_correct_count = updated.correct_count
            progress.quiz_total_count = updated.total_count
            progress.correct_streak = updated.correct_streak
            progress.answered_question_ids = list(updated.answered_question_ids)
            progress.last_reviewed_at = datetime.now(timezone.utc)

        attempt = PracticeAttempt(
            question_id=question_id,
            submitted_answer=answer,
            is_correct=grade.correct,
            feedback=grade.feedback,
            grading_method=grade.method,
            counted_for_progress=counted,
        )
        self.db.add(attempt)
        await self.db.commit()
        await self.db.refresh(attempt)
        await self.db.refresh(progress)

        return {
            "attempt": attempt,
            "progress": progress,
        }

    async def history(self, *, course_id: str, question_id: str) -> list[PracticeAttempt]:
        exists = await self.db.scalar(
            select(func.count(GeneratedQuestion.id))
            .join(Courseware, Courseware.id == GeneratedQuestion.courseware_id)
            .where(GeneratedQuestion.id == question_id, Courseware.course_id == course_id)
        )
        if not exists:
            raise QuestionNotFoundError("题目不存在")
        result = await self.db.execute(
            select(PracticeAttempt)
            .where(PracticeAttempt.question_id == question_id)
            .order_by(PracticeAttempt.created_at.desc())
        )
        return list(result.scalars().all())
