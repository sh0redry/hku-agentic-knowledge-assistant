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
  parser.classifyPage(fakeDocument("Enrollment Add Classes 2026-27 Sem 1"), ""),
  "cart"
);

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
