from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
