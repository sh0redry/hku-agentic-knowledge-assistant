"use strict";

const assert = require("node:assert/strict");
const parser = require("../browser_runtime/extension/weekly_timetable_parser.js");

function cell(text) {
  return { textContent: text, innerText: text };
}

const headers = ["Course", "Section", "Day", "Time", "Venue"];
const row = {
  textContent: "COMP 3230 1B Monday 13:00 - 14:50 CPD-3.04",
  innerText: "COMP 3230 1B Monday 13:00 - 14:50 CPD-3.04",
  querySelectorAll(selector) {
    return selector === ":scope > th, :scope > td"
      ? [cell("COMP 3230"), cell("1B"), cell("Monday"), cell("13:00 - 14:50"), cell("CPD-3.04")]
      : [];
  }
};

assert.deepEqual(parser.parseListRow(row, headers.map(value => value.toLowerCase())), [{
  course_code: "COMP3230",
  section: "1B",
  class_number: null,
  weekday: "monday",
  start_time: "13:00",
  end_time: "14:50",
  room: "CPD-3.04"
}]);

assert.deepEqual(parser.parseTimeRange("9:30AM - 11:20AM"), {
  start_time: "09:30",
  end_time: "11:20"
});
assert.equal(parser.parseWeekday("Wed"), "wednesday");
assert.equal(parser.termLabel("Academic Year 2026-27 Semester 1"), "2026-27 Sem 1");
assert.equal(
  parser.weekRange("Week: 14/09/2026 to 20/09/2026"),
  "14/09/2026 - 20/09/2026"
);
assert.equal(
  parser.termFromWeekRange("Week of 13/09/2026-19/09/2026"),
  "2026-27 Sem 1"
);
assert.equal(parser.termFromWeekRange("Week of 11/01/2027-17/01/2027"), "2026-27 Sem 2");
assert.equal(parser.termFromWeekRange("Week of 12/07/2027-18/07/2027"), null);
assert.deepEqual(parser.parseCourse("ECON2280-[003]-1A 15:00-15:50"), {
  course_code: "ECON2280",
  section: "1A",
  class_number: null
});

const headerCells = headers.map(cell);
const table = {
  querySelectorAll(selector) {
    if (selector === "thead th, tr:first-child th, tr:first-child td") return headerCells;
    if (selector === "tbody tr, tr") return [row];
    if (selector === "tr") return [row];
    return [];
  }
};
const documentObject = {
  body: {
    textContent:
      "HKU My Weekly Schedule Academic Year 2026-27 Semester 1 " +
      "Week: 14/09/2026 to 20/09/2026"
  },
  querySelector(selector) {
    return selector === "input[type='password']" ? null : null;
  },
  querySelectorAll(selector) {
    if (selector === "table") return [table];
    if (selector === "tr") return [row];
    return [];
  }
};
const snapshot = parser.inspect(documentObject, {
  origin: "https://sweb.hku.hk",
  pathname: "/student/servlet/MyWeekly/showTimetable"
});
assert.equal(snapshot.logged_in, true);
assert.equal(snapshot.page_kind, "weekly_timetable");
assert.equal(snapshot.term_label, "2026-27 Sem 1");
assert.equal(snapshot.meeting_count, 1);
assert.equal(snapshot.diagnostics.parser_version, "0.2.1");
assert.equal(snapshot.diagnostics.term_detection_method, "page_label");
assert.equal(snapshot.diagnostics.unparsed_candidate_count, 0);

function visualElement(text, left, top, width = 100, height = 30) {
  return {
    textContent: text,
    innerText: text,
    getBoundingClientRect() {
      return { left, right: left + width, top, bottom: top + height };
    }
  };
}

const dayNames = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const visualHeaders = dayNames.map((name, index) => visualElement(name, index * 100, 20));
const visualCards = [
  visualElement("FINA2320-1C\n09:00-10:50\nLE3", 205, 100, 90, 90),
  visualElement("ECON2280-[003]-1A\n15:00-15:50", 205, 400, 90, 30),
  visualElement("COMP3230-1B\n13:00-14:50\nCPD-3.04", 505, 300, 90, 90),
  visualElement("ECON2280-1A\n09:00-11:50\nMB217", 505, 100, 90, 120)
];
const visualDocument = {
  body: { textContent: "MY TIMETABLE Week of 13/09/2026-19/09/2026" },
  querySelector() { return null; },
  querySelectorAll(selector) {
    if (selector === "table") return [];
    if (selector === "tr") return [];
    if (selector === "th, td, div, span") return visualHeaders;
    if (selector === "td, div, span, a") return [...visualHeaders, ...visualCards];
    return [];
  }
};
const visualSnapshot = parser.inspect(visualDocument, {
  origin: "https://sweb.hku.hk",
  pathname: "/student/servlet/MyWeekly/showTimetable"
});
assert.equal(visualSnapshot.term_label, "2026-27 Sem 1");
assert.equal(visualSnapshot.week_range, "13/09/2026 - 19/09/2026");
assert.equal(visualSnapshot.diagnostics.term_detection_method, "inferred_from_week_start");
assert.equal(visualSnapshot.meeting_count, 4);
assert.equal(visualSnapshot.diagnostics.meeting_candidate_count, 4);
assert.equal(visualSnapshot.diagnostics.unparsed_candidate_count, 0);
assert.deepEqual(visualSnapshot.meetings[0], {
  course_code: "FINA2320",
  section: "1C",
  class_number: null,
  weekday: "tuesday",
  start_time: "09:00",
  end_time: "10:50",
  room: "LE3"
});
assert.equal(visualSnapshot.meetings[1].course_code, "ECON2280");
assert.equal(visualSnapshot.meetings[1].section, "1A");
assert.equal(visualSnapshot.meetings[1].weekday, "tuesday");
assert.equal(visualSnapshot.meetings[2].weekday, "friday");
assert.equal(visualSnapshot.meetings[3].room, "MB217");

assert.throws(
  () => parser.inspect(documentObject, { origin: "https://evil.example" }),
  error => error.code === "WRONG_TIMETABLE_ORIGIN"
);

console.log("HKU weekly timetable parser tests passed.");
