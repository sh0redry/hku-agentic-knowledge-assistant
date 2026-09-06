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
  textContent: "2026-27 Sem 1 Temporary Course List",
  compareDocumentPosition(element) {
    return element === cartRow ? 4 : 0;
  }
};
const cartRow = {
  querySelectorAll() {
    return [
      { textContent: "COMP 2119-1A (12345)" },
      { textContent: "Data structures" },
      { textContent: "6.00" }
    ];
  }
};
const cartTable = {
  querySelectorAll(selector) {
    if (selector === "thead th, tr:first-child th") {
      return [
        { textContent: "Class" },
        { textContent: "Description" },
        { textContent: "Units" }
      ];
    }
    return [cartRow];
  }
};
const populatedCartDocument = {
  body: { textContent: "2026-27 Sem 1 Temporary Course List COMP 2119-1A (12345)" },
  querySelectorAll(selector) {
    if (selector === "table") return [cartTable];
    if (selector === "h1, h2, h3, h4, th, td, span, div") return [cartMarker];
    return [];
  }
};

assert.deepEqual(parser.extractCourses(populatedCartDocument, "cart"), [
  { course_code: "COMP2119", section: "1A", class_number: "12345" }
]);

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
