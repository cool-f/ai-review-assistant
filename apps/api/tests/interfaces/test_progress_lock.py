import asyncio

from review_assistant.interfaces.http.routes.progress import (
    _lock_knowledge_point_in_course,
)


def test_manual_progress_update_locks_course_scoped_parent_row() -> None:
    sentinel = object()

    class Result:
        def scalar_one_or_none(self):
            return sentinel

    class RecordingDb:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    async def run():
        db = RecordingDb()
        value = await _lock_knowledge_point_in_course(db, "kp-1", "course-1")
        return value, str(db.statement)

    value, statement = asyncio.run(run())

    assert value is sentinel
    assert "FOR UPDATE" in statement
    assert "coursewares.course_id" in statement
