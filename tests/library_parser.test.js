"use strict";

const assert = require("node:assert/strict");
const parser = require("../browser_runtime/extension/library_parser.js");

function resultNode(id, title, href, text) {
  const anchor = {
    textContent: title,
    getAttribute(name) { return name === "href" ? href : null; }
  };
  return {
    id,
    innerText: text,
    querySelector() { return anchor; }
  };
}

const valid = resultNode(
  "SEARCH_RESULT_RECORDID_alma991234",
  "Artificial intelligence",
  "https://julac-hku.primo.exlibrisgroup.com/discovery/fulldisplay?docid=alma991234&query=secret&vid=852JULAC_HKU:HKU",
  "1\nBOOK\nArtificial intelligence\nHulick, Kathryn\n2016\nAvailable at Main Library"
);
const researchDocument = {
  querySelector() { return {}; },
  querySelectorAll(selector) { return selector.startsWith("[id^=") ? [valid] : []; }
};
const research = parser.parseResearch(researchDocument, {
  origin: "https://julac-hku.primo.exlibrisgroup.com",
  pathname: "/discovery/search"
}, 10);
assert.equal(research.result_count, 1);
assert.equal(research.results[0].record_id, "alma991234");
assert.equal(research.results[0].resource_type, "book");
assert.match(research.results[0].availability_label, /Available at/);
assert.equal(research.results[0].detail_url.includes("secret"), false);
assert.deepEqual([...new URL(research.results[0].detail_url).searchParams.keys()], ["docid", "vid", "lang"]);

const liveLikeAnchor = {
  textContent: "",
  innerText: "",
  getAttribute(name) {
    if (name === "href") return "/discovery/fulldisplay?context=L&vid=852JULAC_HKU:HKU&docid=alma998765";
    if (name === "aria-label") return "View full display details";
    return null;
  }
};
const liveLikeNode = {
  id: "SEARCH_RESULT_RECORDID_alma998765",
  innerText: "2\nBOOK\nReliable systems\nAuthor name\nOnline access",
  querySelector(selector) {
    return selector.includes("a[") ? liveLikeAnchor : null;
  }
};
const liveLikeResearch = parser.parseResearch({
  body: { textContent: "Search results" },
  querySelectorAll() { return [liveLikeNode]; }
}, {
  origin: "https://julac-hku.primo.exlibrisgroup.com",
  pathname: "/discovery/search"
}, 10);
assert.equal(liveLikeResearch.results[0].title, "Reliable systems");
assert.equal(liveLikeResearch.diagnostics.missing_result_title_candidate_count, 0);

const loadingResearch = parser.parseResearch({
  body: { textContent: "Loading search results" },
  querySelectorAll() { return []; }
}, {
  origin: "https://julac-hku.primo.exlibrisgroup.com",
  pathname: "/discovery/search"
}, 10);
assert.equal(loadingResearch.diagnostics.results_marker_found, false);

const emptyResearch = parser.parseResearch({
  body: { textContent: "No records found" },
  querySelectorAll() { return []; }
}, {
  origin: "https://julac-hku.primo.exlibrisgroup.com",
  pathname: "/discovery/search"
}, 10);
assert.equal(emptyResearch.diagnostics.results_marker_found, true);
assert.equal(emptyResearch.diagnostics.empty_results_marker_found, true);

assert.throws(
  () => parser.parseResearch(researchDocument, { origin: "https://evil.example", pathname: "/discovery/search" }),
  error => error.code === "WRONG_LIBRARY_PAGE"
);

function cell(text, backgroundColor = "") {
  return {
    textContent: text,
    innerText: text,
    className: "",
    style: { backgroundColor },
    getAttribute() { return null; }
  };
}
function row(cells) {
  return { querySelectorAll() { return cells; } };
}
const headerRow = row([cell("Floor"), cell("Facility"), cell("09:00 - 10:30")]);
const availableRow = row([cell("4/F"), cell("Single Study Room 422"), cell("", "rgb(91, 159, 11)")]);
const bookedRow = row([cell("4/F"), cell("Single Study Room 423"), cell("", "rgb(227, 99, 99)")]);
const spaceDocument = {
  body: { textContent: "Facilities Booking System 2026-09-20 Booked Available" },
  querySelectorAll(selector) { return selector === "table tr" ? [headerRow, availableRow, bookedRow] : []; }
};
const spaces = parser.parseSpaceAvailability(spaceDocument, {
  origin: "https://booking.lib.hku.hk",
  pathname: "/FView.aspx"
});
assert.equal(spaces.date, "2026-09-20");
assert.equal(spaces.available_slot_count, 1);
assert.deepEqual(spaces.available_slots[0], {
  floor: "4/F",
  room: "Single Study Room 422",
  start_time: "09:00",
  end_time: "10:30",
  status: "available"
});
assert.equal(spaces.diagnostics.table_matrix_found, true);
assert.equal(spaces.diagnostics.slot_candidate_count, 2);

const fullyBookedDocument = {
  body: { textContent: "Facilities Booking System 2026-09-20 Booked Available" },
  querySelectorAll(selector) { return selector === "table tr" ? [headerRow, bookedRow] : []; }
};
const fullyBooked = parser.parseSpaceAvailability(fullyBookedDocument, {
  origin: "https://booking.lib.hku.hk",
  pathname: "/FView.aspx"
});
assert.equal(fullyBooked.available_slot_count, 0);
assert.equal(fullyBooked.diagnostics.slot_candidate_count, 1);
assert.equal(fullyBooked.diagnostics.incomplete_available_slot_candidate_count, 0);

assert.throws(
  () => parser.parseSpaceAvailability(spaceDocument, {
    origin: "https://lib.hku.hk",
    pathname: "/hkulauth/legacy/authMain"
  }),
  error => error.code === "LIBRARY_LOGIN_REQUIRED"
);

console.log("HKU Library parser synthetic tests passed.");
