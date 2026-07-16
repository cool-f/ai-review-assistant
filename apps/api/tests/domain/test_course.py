import pytest

from review_assistant.domain.course import CourseContents, CourseNotEmptyError


def test_non_empty_course_cannot_be_deleted_silently() -> None:
    with pytest.raises(CourseNotEmptyError, match="不能直接删除"):
        CourseContents(coursewares=1).ensure_deletable()


def test_empty_course_can_be_deleted() -> None:
    CourseContents().ensure_deletable()


def test_course_with_only_folders_is_not_empty() -> None:
    with pytest.raises(CourseNotEmptyError):
        CourseContents(folders=1).ensure_deletable()
