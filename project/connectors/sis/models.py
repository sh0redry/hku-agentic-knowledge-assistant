from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExpectedCourseSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_code: str = Field(min_length=3, max_length=20)
    section: str = Field(min_length=1, max_length=40)

    @field_validator("course_code")
    @classmethod
    def normalize_course_code(cls, value: str) -> str:
        normalized = re.sub(r"\s+", "", value).upper()
        if not re.fullmatch(r"[A-Z]{2,8}\d{3,5}[A-Z]?", normalized):
            raise ValueError("Invalid HKU-style course code.")
        return normalized

    @field_validator("section")
    @classmethod
    def normalize_section(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9-]+", normalized):
            raise ValueError("Invalid SIS section identifier.")
        return normalized

    def intent_key(self) -> tuple[str, str]:
        return self.course_code, self.section


class CourseSelection(ExpectedCourseSelection):
    """A concrete SIS offering; class_number is observed from SIS, not user intent."""

    class_number: str = Field(min_length=1, max_length=30)

    @field_validator("class_number")
    @classmethod
    def normalize_class_number(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"\d{3,8}", normalized):
            raise ValueError("Class number must contain 3 to 8 digits.")
        return normalized

    def comparison_key(self) -> tuple[str, str, str]:
        return self.course_code, self.section, self.class_number


class SISPreflightRequest(BaseModel):
    origin: str = "https://sis-main.hku.hk"
    logged_in: bool = True
    page_kind: str = "cart"
    term_label: str = Field(pattern=r"^\d{4}-\d{2}\s+Sem\s+[12]$")
    current_term_label: str
    expected_courses: list[CourseSelection] = Field(min_length=1)
    visible_courses: list[CourseSelection]


class SISLivePreflightRequest(BaseModel):
    """Trusted user intent; live SIS state is always supplied by the browser connector."""

    model_config = ConfigDict(extra="forbid")

    term_label: str = Field(pattern=r"^\d{4}-\d{2}\s+Sem\s+[12]$")
    expected_courses: list[ExpectedCourseSelection] = Field(min_length=1, max_length=50)


class SISNavigationRequest(BaseModel):
    """Optional validated term intent; no URL, selector, or script is accepted."""

    model_config = ConfigDict(extra="forbid")

    term_label: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}\s+Sem\s+[12]$",
    )


Weekday = Literal[
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


class SISTimetableMeeting(ExpectedCourseSelection):
    class_number: str | None = Field(default=None, pattern=r"^\d{3,8}$")
    weekday: Weekday
    start_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    room: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.end_time <= self.start_time:
            raise ValueError("Meeting end_time must be later than start_time.")
        return self


class SISExamEntry(ExpectedCourseSelection):
    exam_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str | None = Field(
        default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    end_time: str | None = Field(
        default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    venue: str | None = Field(default=None, max_length=160)
    seat: str | None = Field(default=None, max_length=80)


class SISTimetableSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term_label: str = Field(pattern=r"^\d{4}-\d{2}\s+Sem\s+[12]$")


class SISNextClassRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term_label: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}\s+Sem\s+[12]$"
    )
    as_of: datetime | None = None
    days_ahead: int = Field(default=14, ge=1, le=28)


class SISFreeSlotsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term_label: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}\s+Sem\s+[12]$"
    )
    weekdays: list[Weekday] = Field(
        default_factory=lambda: [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
        ]
    )
    window_start: str = Field(
        default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    window_end: str = Field(
        default="18:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    minimum_minutes: int = Field(default=60, ge=15, le=720)

    @model_validator(mode="after")
    def validate_window(self):
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be later than window_start.")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("weekdays must not contain duplicates.")
        return self


class SISTimetableConflictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term_label: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}\s+Sem\s+[12]$"
    )
    candidate_meetings: list[SISTimetableMeeting] = Field(min_length=1, max_length=50)


class SISExamStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term_label: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}\s+Sem\s+[12]$"
    )
