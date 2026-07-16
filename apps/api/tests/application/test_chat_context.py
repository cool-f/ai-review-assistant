from review_assistant.application.chat.service import ChatService, assemble_model_messages


class _EmptyRows:
    def __iter__(self):
        return iter(())


class _CapturingDb:
    def __init__(self):
        self.statement = None
        self.params = None

    async def execute(self, statement, params=None):
        self.statement = statement
        self.params = params
        return _EmptyRows()


def test_current_user_prompt_is_sent_exactly_once() -> None:
    messages = assemble_model_messages(
        "system",
        [{"role": "user", "content": "当前问题"}],
        "当前问题",
    )
    assert sum(message["content"] == "当前问题" for message in messages) == 1


def test_citations_keep_courseware_and_page_location() -> None:
    citations = ChatService._build_citations([], [{
        "courseware_id": "cw-1", "courseware_title": "高等数学",
        "knowledge_point_id": "kp-1", "page_number": 12,
        "content": "导数定义", "similarity": 0.91,
    }])
    assert citations[0]["courseware_title"] == "高等数学"
    assert citations[0]["page_number"] == 12


def test_course_wide_vector_search_is_always_course_scoped() -> None:
    import asyncio

    db = _CapturingDb()
    service = ChatService(db)
    rows = asyncio.run(service._vector_search_chunks(
        [0.0] * 1024,
        course_id="course-1",
        courseware_id=None,
        limit=5,
    ))

    assert rows == []
    assert "cw.course_id = :course_id" in str(db.statement)
    assert db.params["course_id"] == "course-1"
