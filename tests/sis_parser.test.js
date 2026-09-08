"use strict";

const assert = require("node:assert/strict");
const parser = require("../browser_runtime/extension/sis_parser.js");

assert.deepEqual(
  parser.parseCourseRow(
    ["COMP 2119", "1A", "12345"],
    ["Course", "Section", "Class Nbr"]
  ),
  { course_code: "COMP2119", section: "1A", class_number: "12345" }
);

assert.deepEqual(
  parser.parseCourseRow(
    ["COMP 1110-1A (4360)", "Computing and data science", "6.00"],
    ["Class", "Description", "Units"]
  ),
  { course_code: "COMP1110", section: "1A", class_number: "4360" }
);

assert.equal(
  parser.parseCourseRow(["COMP2119", "1A", ""], ["Course", "Section", "Class Nbr"]),
  null
);

function fakeDocument(text, password = false) {
  return {
    body: { textContent: text },
    querySelector(selector) {
      return selector === "input[type='password']" && password ? {} : null;
    }
  };
}

assert.equal(parser.classifyPage(fakeDocument("Temporary Course List"), ""), "cart");
assert.equal(parser.classifyPage(fakeDocument("Sign In", true), ""), "login");
assert.equal(parser.classifyPage(fakeDocument("Unrecognized content"), ""), "unknown");
assert.equal(
  parser.selectedTerm(fakeDocument("Enrollment Add Classes 2026-27 Sem 2")),
  "2026-27 Sem 2"
);

assert.equal(
  parser.classifyPage(fakeDocument("Enrollment Add Classes 2026-27 Sem 1"), ""),
  "cart"
);

const cartMarker = {
  textContent: "2026-27 Sem 2 Temporary Course List",
  compareDocumentPosition(element) {
    return element === cartRow ? 4 : 0;
  }
};
const cartRow = {
  querySelectorAll() {
    return [
      { textContent: "" },
      { textContent: "COMP 3297-2B (1725)" },
      { textContent: "Th 10:00 - 11:50 Tu 09:00 - 09:50" },
      { textContent: "CYCP1" },
      { textContent: "Staff" },
      { textContent: "6.00" },
      { textContent: "Open" }
    ];
  }
};
const cartTable = {
  querySelectorAll(selector) {
    if (selector === "thead th, tr:first-child th") {
      return [
        { textContent: "Delete" },
        { textContent: "Days/Times" },
        // Deliberately misaligned, as can happen when an outer PeopleSoft
        // presentation table contributes headers for a nested course row.
        { textContent: "Class" },
        { textContent: "Room" },
        { textContent: "Instructor" },
        { textContent: "Units" },
        { textContent: "Status" }
      ];
    }
    return [cartRow];
  }
};
const classLink = {
  textContent: "COMP 3297-2B (1725)",
  closest(selector) {
    return selector === "tr" ? cartRow : null;
  }
};
const populatedCartDocument = {
  body: {
    // PeopleSoft may keep the empty-state template in hidden DOM even when a row is visible.
    textContent:
      "Your Temporary Course List is empty. 2026-27 Sem 2 Temporary Course List COMP 3297-2B (1725)"
  },
  querySelectorAll(selector) {
    if (selector === "table") return [cartTable];
    if (selector === "a") return [classLink];
    if (selector === "h1, h2, h3, h4, th, td, span, div") return [cartMarker];
    return [];
  }
};

assert.deepEqual(parser.extractCourses(populatedCartDocument, "cart"), [
  { course_code: "COMP3297", section: "2B", class_number: "1725" }
]);

const linkOnlyCartDocument = {
  body: { textContent: "2026-27 Sem 2 Temporary Course List" },
  querySelectorAll(selector) {
    if (selector === "table") return [];
    if (selector === "a") return [classLink];
    if (selector === "h1, h2, h3, h4, th, td, span, div") return [cartMarker];
    return [];
  }
};

assert.deepEqual(parser.extractCourses(linkOnlyCartDocument, "cart"), [
  { course_code: "COMP3297", section: "2B", class_number: "1725" }
]);

const broadLayoutTable = {
  contains(element) {
    return element === cartMarker || element === cartRow;
  }
};
const scheduleMarkerInBroadTable = {
  textContent: "My 2026-27 Sem 2 Class Schedule",
  closest(selector) {
    return selector === "table" ? broadLayoutTable : null;
  },
  compareDocumentPosition() {
    return 0;
  }
};
const broadLayoutDocument = {
  body: { textContent: "2026-27 Sem 2 Temporary Course List Class Schedule" },
  querySelectorAll(selector) {
    if (selector === "a") return [classLink];
    if (selector === "h1, h2, h3, h4, th, td, span, div") {
      return [cartMarker, scheduleMarkerInBroadTable];
    }
    return [];
  }
};

assert.deepEqual(parser.extractCourses(broadLayoutDocument, "cart"), [
  { course_code: "COMP3297", section: "2B", class_number: "1725" }
]);

const scheduledRow = {};
const scheduledLink = {
  textContent: "COMP 1110-1A (4360)",
  closest(selector) {
    return selector === "tr" ? scheduledRow : null;
  }
};
const exactScheduleMarker = {
  textContent: "My 2026-27 Sem 1 Class Schedule",
  compareDocumentPosition(element) {
    return element === scheduledRow ? 4 : 0;
  }
};
const separatedCoursesDocument = {
  body: { textContent: "2026-27 Sem 1 Temporary Course List My Class Schedule" },
  querySelectorAll(selector) {
    if (selector === "a") return [classLink, scheduledLink];
    if (selector === "h1, h2, h3, h4, th, td, span, div") {
      return [cartMarker, exactScheduleMarker];
    }
    return [];
  }
};

assert.deepEqual(parser.extractCartCourseGroups(separatedCoursesDocument), {
  temporary: [{ course_code: "COMP3297", section: "2B", class_number: "1725" }],
  schedule: [{ course_code: "COMP1110", section: "1A", class_number: "4360" }],
  unclassified: []
});

assert.deepEqual(
  parser.chooseBestSnapshot([
    { page_kind: "status", term_label: null, course_count: 0, logged_in: true },
    {
      page_kind: "cart",
      term_label: "2026-27 Sem 1",
      course_count: 0,
      logged_in: null
    }
  ]),
  {
    page_kind: "cart",
    term_label: "2026-27 Sem 1",
    course_count: 0,
    logged_in: true
  }
);

console.log("SIS parser synthetic tests passed.");
