from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    term: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=2000)


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    term: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class CourseResponse(BaseModel):
    id: str
    name: str
    term: str
    description: str
    courseware_count: int = 0
    homework_count: int = 0
    folder_count: int = 0
    session_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
