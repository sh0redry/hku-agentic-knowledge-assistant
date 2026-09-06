from __future__ import annotations

from collections import defaultdict
from typing import TypeAlias

from connectors.sis.models import CourseSelection, ExpectedCourseSelection
from connectors.sis.protocol import SIS_ORIGIN


ComparableCourse: TypeAlias = CourseSelection | ExpectedCourseSelection
ComparisonKey: TypeAlias = tuple[str, str] | tuple[str, str, str]


def _key(course: ComparableCourse, match_class_number: bool) -> ComparisonKey:
    if match_class_number:
        if not isinstance(course, CourseSelection):
            raise TypeError("Exact preflight comparison requires concrete class numbers.")
        return course.comparison_key()
    return course.intent_key()


def _course_map(
    courses: list[ComparableCourse], match_class_number: bool
) -> dict[ComparisonKey, ComparableCourse]:
    return {_key(course, match_class_number): course for course in courses}


def _duplicates(courses: list[ComparableCourse], match_class_number: bool) -> list[dict]:
    grouped: dict[ComparisonKey, list[ComparableCourse]] = defaultdict(list)
    for course in courses:
        grouped[_key(course, match_class_number)].append(course)
    return [
        course.model_dump()
        for key in sorted(grouped)
        if len(grouped[key]) > 1
        for course in grouped[key]
    ]


def evaluate_preflight(
    *,
    requested_term_label: str,
    expected_courses: list[ComparableCourse],
    origin: str | None,
    logged_in: bool | None,
    page_kind: str,
    current_term_label: str | None,
    visible_courses: list[CourseSelection],
    simulated: bool,
    match_class_number: bool = True,
) -> dict:
    """Compare trusted intent with a structured snapshot without performing SIS writes."""

    issues: list[str] = []
    warnings: list[str] = []
    if simulated:
        warnings.append("SIMULATED RESULT: no browser or HKU SIS connection was used.")

    if origin != SIS_ORIGIN:
        issues.append(f"Origin must be exactly {SIS_ORIGIN}.")
    if logged_in is not True:
        issues.append("SIS session is not confirmed as logged in.")
    if page_kind != "cart":
        issues.append("Open the Temporary Course List before preflight.")

    term_match = current_term_label == requested_term_label
    if not term_match:
        issues.append("Current SIS term does not match the requested term.")

    expected = _course_map(expected_courses, match_class_number)
    visible = _course_map(visible_courses, match_class_number)
    matched_keys = expected.keys() & visible.keys()
    missing_keys = expected.keys() - visible.keys()
    unexpected_keys = visible.keys() - expected.keys()

    # Live matching returns concrete SIS rows, revealing the class number only
    # after Course + Section have matched the user's intent.
    matched = [visible[key].model_dump() for key in sorted(matched_keys)]
    missing = [expected[key].model_dump() for key in sorted(missing_keys)]
    unexpected = [visible[key].model_dump() for key in sorted(unexpected_keys)]
    duplicate_expected = _duplicates(expected_courses, match_class_number)
    duplicate_visible = _duplicates(visible_courses, match_class_number)

    if duplicate_expected:
        issues.append("The expected course list contains duplicate entries.")
    if duplicate_visible:
        issues.append(
            "The SIS cart contains more than one class number for the same course and section."
        )
    if missing:
        issues.append(
            "Expected course/section entries are missing from the cart."
            if not match_class_number
            else "Expected course/section/class entries are missing from the cart."
        )
    if unexpected:
        issues.append(
            "The cart contains unexpected course/section entries."
            if not match_class_number
            else "The cart contains unapproved course/section/class entries."
        )

    ready = not issues
    return {
        "ok": ready,
        "ready": ready,
        "read_only": True,
        "simulated": simulated,
        "sis_write_requests_sent": 0,
        "comparison_fields": (
            ["course_code", "section", "class_number"]
            if match_class_number
            else ["course_code", "section"]
        ),
        "page_kind": page_kind,
        "requested_term_label": requested_term_label,
        "term_label": current_term_label,
        "term_match": term_match,
        "expected_courses": [item.model_dump() for item in expected_courses],
        "visible_courses": [item.model_dump() for item in visible_courses],
        "matched_courses": matched,
        "missing_courses": missing,
        "unexpected_courses": unexpected,
        "duplicate_expected_courses": duplicate_expected,
        "duplicate_visible_courses": duplicate_visible,
        # Compatibility aliases for the original simulator response.
        "missing": missing,
        "unexpected": unexpected,
        "issues": issues,
        "warnings": warnings,
    }
