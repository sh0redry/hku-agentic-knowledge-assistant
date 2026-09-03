from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class CourseSelection(BaseModel):
    course_code: str = Field(min_length=3, max_length=20)
    section: str = Field(min_length=1, max_length=40)
    class_number: str = Field(min_length=1, max_length=30)

    @field_validator("course_code")
    @classmethod
    def normalize_course_code(cls, value: str) -> str:
        normalized = re.sub(r"\s+", "", value).upper()
        if not re.fullmatch(r"[A-Z]{2,8}\d{3,5}[A-Z]?", normalized):
            raise ValueError("Invalid HKU-style course code.")
        return normalized

    @field_validator("section", "class_number")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().upper()

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
