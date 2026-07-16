from dataclasses import dataclass


class CourseNotEmptyError(ValueError):
    """Raised when deleting a course would silently destroy study records."""


@dataclass(frozen=True)
class CourseContents:
    coursewares: int = 0
    homeworks: int = 0
    folders: int = 0
    sessions: int = 0

    @property
    def is_empty(self) -> bool:
        return (
            self.coursewares == 0
            and self.homeworks == 0
            and self.folders == 0
            and self.sessions == 0
        )

    def ensure_deletable(self) -> None:
        if not self.is_empty:
            raise CourseNotEmptyError("课程中仍有课件、作业、文件夹或对话，不能直接删除")
