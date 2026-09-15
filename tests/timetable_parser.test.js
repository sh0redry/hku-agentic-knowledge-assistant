"use strict";

const assert = require("node:assert/strict");
const parser = require("../browser_runtime/extension/sis_parser.js");

assert.deepEqual(parser.parseDayTimes("Mo 13:00 - 14:50\nWe 09:00 - 10:50"), [
  { weekday: "monday", start_time: "13:00", end_time: "14:50" },
  { weekday: "wednesday", start_time: "09:00", end_time: "10:50" }
]);

const scheduleRow = {
  querySelectorAll(selector) {
    if (selector !== ":scope > th, :scope > td") return [];
    return [
      { textContent: "COMP 3230-1B (1778)" },
      { textContent: "Principles of operating systems" },
      { textContent: "Fr 13:00 - 14:50\nMo 13:00 - 14:50" },
      { textContent: "CPD-3.04\nCPD-3.04" },
      { textContent: "Staff" }
    ];
  }
};
const scheduleLink = {
  textContent: "COMP 3230-1B (1778)",
  closest(selector) { return selector === "tr" ? scheduleRow : null; }
};
const scheduleMarker = {
  textContent: "My 2026-27 Sem 1 Class Schedule",
  closest() { return null; },
  compareDocumentPosition(element) { return element === scheduleRow ? 4 : 0; }
};
const scheduleDocument = {
  body: { textContent: "My 2026-27 Sem 1 Class Schedule" },
  querySelectorAll(selector) {
    if (selector === "a") return [scheduleLink];
    if (selector === "h1, h2, h3, h4, th, td, span, div") return [scheduleMarker];
    return [];
  }
};

assert.deepEqual(parser.extractScheduleMeetings(scheduleDocument), [
  {course_code: "COMP3230", section: "1B", class_number: "1778", weekday: "friday", start_time: "13:00", end_time: "14:50", room: "CPD-3.04"},
  {course_code: "COMP3230", section: "1B", class_number: "1778", weekday: "monday", start_time: "13:00", end_time: "14:50", room: "CPD-3.04"}
]);

const examCells = [
  { textContent: "COMP 3297-2B", getAttribute: () => "course" },
  { textContent: "18/12/2026", getAttribute: () => "exam date" },
  { textContent: "09:30 - 11:30", getAttribute: () => "exam time" },
  { textContent: "CPD-LG.07", getAttribute: () => "venue" },
  { textContent: "A12", getAttribute: () => "seat" }
];
const examRow = {
  querySelectorAll(selector) {
    return selector === ":scope > th, :scope > td" ? examCells : [];
  }
};
const examDocument = {
  body: { textContent: "Examination Timetables Exam Date Exam Time" },
  querySelector(selector) { return selector === "input[type='password']" ? null : null; },
  querySelectorAll(selector) { return selector === "tr" ? [examRow] : []; }
};
const examKind = parser.classifyPage(examDocument, "");
const entries = parser.extractExamEntries(examDocument);
assert.equal(examKind, "exam_schedule");
assert.deepEqual(entries, [{
  course_code: "COMP3297", section: "2B", exam_date: "2026-12-18",
  start_time: "09:30", end_time: "11:30", venue: "CPD-LG.07", seat: "A12"
}]);
assert.equal(parser.examPublicationState(examDocument, examKind, entries), "published");

const unpublishedDocument = { body: { textContent: "Examination Timetables not yet published" } };
assert.equal(parser.examPublicationState(unpublishedDocument, "exam_schedule", []), "not_published");

console.log("SIS timetable parser tests passed.");
