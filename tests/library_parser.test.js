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

const detailTitleNode = { innerText: "Artificial intelligence", textContent: "Artificial intelligence" };
const detailCells = [cell("Publication"), cell("Amsterdam : North-Holland, 1970-")];
const detailRow = { querySelectorAll() { return detailCells; } };
const operationalRows = [
  { querySelectorAll() { return [cell("QR"), cell("READING LIST EXPORT BIBTEX CITATION")]; } },
  { querySelectorAll() { return [cell("Elsevier SD Complete Freedom Collection 2024"), cell("Available from 01/01/1995. SHOW LICENSE")]; } },
  { querySelectorAll() { return [cell("To request, please"), cell("Sign in")]; } },
  { querySelectorAll() { return [cell("Main Library"), cell("Available, Main Serials; S 001.5 A79 I61")]; } },
  { querySelectorAll() { return [cell("Summary holdings:"), cell("v.6 (1975)-v.150 (2003)")]; } },
  { querySelectorAll() { return [cell("Item in place (0 requests)"), cell("Loanable v.72 1995")]; } }
];
const onlineAccess = {
  innerText: "Online access, opens in a new window",
  textContent: "Online access, opens in a new window",
  getAttribute(name) { return name === "href" ? "https://proxy.example/licensed" : null; }
};
const physicalAccess = {
  innerText: "Available at Main Library Main Serials",
  textContent: "Available at Main Library Main Serials",
  getAttribute() { return null; }
};
const detailDocument = {
  body: { innerText: "JOURNAL\nArtificial intelligence\nDetails\nOnline access\nAvailability" },
  querySelectorAll(selector) {
    if (selector === "[data-field-selector='title']") return [detailTitleNode];
    if (selector === "table tr") return [detailRow, ...operationalRows];
    if (selector === "a") return [onlineAccess, physicalAccess];
    return [];
  }
};
const detail = parser.parseResearchDetail(detailDocument, {
  origin: "https://julac-hku.primo.exlibrisgroup.com",
  pathname: "/discovery/fulldisplay",
  href: "https://julac-hku.primo.exlibrisgroup.com/discovery/fulldisplay?docid=alma991234&vid=852JULAC_HKU:HKU&lang=en"
});
assert.equal(detail.record_id, "alma991234");
assert.equal(detail.title, "Artificial intelligence");
assert.equal(detail.metadata[0].label, "Publication");
assert.equal(detail.metadata.length, 1);
assert.equal(detail.access_options.length, 2);
assert.equal(detail.access_options[0].kind, "online");
assert.equal(detail.access_options[0].label, "Online access");
assert.equal(detail.diagnostics.unsafe_access_link_candidate_count, 1);
assert.equal(Object.hasOwn(detail.access_options[0], "url"), false);

const loadingDetail = parser.parseResearchDetail({
  body: { innerText: "Full display page\nDetails\nLoading" },
  querySelectorAll(selector) {
    if (selector === "h1") return [{ innerText: "Full display page" }];
    return [];
  }
}, {
  origin: "https://julac-hku.primo.exlibrisgroup.com",
  pathname: "/discovery/fulldisplay",
  href: "https://julac-hku.primo.exlibrisgroup.com/discovery/fulldisplay?docid=alma991234"
});
assert.equal(loadingDetail.title, null);
assert.equal(loadingDetail.diagnostics.detail_marker_found, false);
assert.equal(loadingDetail.diagnostics.metadata_field_count, 0);

const noisyAccessNodes = [
  { innerText: "VIEW ONLINE", getAttribute() { return null; } },
  { innerText: "Artificial intelligence. Available at Main Library Main Serials (S 001.5 A79 I61)", getAttribute() { return null; } },
  { innerText: "Artificial intelligence. Online access", getAttribute() { return null; } },
  { innerText: "Artificial intelligence. Available at Main Library Main Serials (S 001.5 A79 I61) Artificial intelligence. Online access View Journal Contents", getAttribute() { return null; } },
  { innerText: "Main Library", getAttribute() { return null; } },
  { innerText: "TOP SEND TO SEARCH INSIDE VIEW ONLINE GET IT REQUEST FROM OTHER INSTITUTIONS DETAILS LINKS VIRTUAL BROWSE", getAttribute() { return null; } }
];
const noisyDetailDocument = {
  body: { innerText: "JOURNAL\nArtificial intelligence.\nDetails\nAvailability\nOnline access" },
  querySelectorAll(selector) {
    if (selector === "[data-field-selector='title']") return [{ innerText: "Artificial intelligence." }];
    if (selector === "table tr") return [detailRow];
    if (selector === "a") return noisyAccessNodes;
    return [];
  }
};
const noisyDetail = parser.parseResearchDetail(noisyDetailDocument, {
  origin: "https://julac-hku.primo.exlibrisgroup.com",
  pathname: "/discovery/fulldisplay",
  href: "https://julac-hku.primo.exlibrisgroup.com/discovery/fulldisplay?docid=alma991234"
});
assert.deepEqual(noisyDetail.access_options.map((option) => option.label), [
  "VIEW ONLINE",
  "Available at Main Library Main Serials (S 001.5 A79 I61)",
  "Online access"
]);

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
function selectedOption(text) {
  return { textContent: text, innerText: text, value: text, selected: true };
}
const bookingSelects = [
  { options: [selectedOption("Main Library")], selectedIndex: 0 },
  { options: [selectedOption("Single Study Room (3 sessions)")], selectedIndex: 0 },
  { options: [selectedOption("2026-09-20 (Sun)")], selectedIndex: 0 }
];
const spaceDocument = {
  body: { textContent: "Facilities Booking System 2026-09-20 Booked Available Last Updated: 2026-09-19 12:34:56" },
  querySelectorAll(selector) {
    if (selector === "table tr") return [headerRow, availableRow, bookedRow];
    if (selector === "select") return bookingSelects;
    return [];
  }
};
const spaces = parser.parseSpaceAvailability(spaceDocument, {
  origin: "https://booking.lib.hku.hk",
  pathname: "/FView.aspx"
});
assert.equal(spaces.date, "2026-09-20");
assert.equal(spaces.location, "Main Library");
assert.equal(spaces.booking_facility_type, "Single Study Room (3 sessions)");
assert.equal(spaces.source_last_updated_at, "2026-09-19 12:34:56");
assert.equal(spaces.result_set_complete, true);
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

function filterSelect(values, selectedIndex = 0) {
  const options = values.map((text, index) => ({
    textContent: text,
    innerText: text,
    value: text,
    selected: index === selectedIndex
  }));
  const select = {
    options,
    selectedIndex,
    dispatchEvent() {},
    ownerDocument: { defaultView: { Event: class Event {} } }
  };
  Object.defineProperty(select, "value", {
    get() { return options[select.selectedIndex]?.value || ""; },
    set(value) {
      const index = options.findIndex((option) => option.value === value);
      if (index >= 0) {
        select.selectedIndex = index;
        options.forEach((option, optionIndex) => { option.selected = optionIndex === index; });
      }
    }
  });
  return select;
}
const configurableSelects = [
  filterSelect(["- Please Select -", "Main Library", "Chi Wah Learning Commons"]),
  filterSelect(["- Please Select -", "Single Study Room (3 sessions)", "Study Room"]),
  filterSelect(["- Please Select -", "2026-09-20 (Sun)", "2026-09-23 (Wed)"])
];
let searchClicks = 0;
const searchControl = {
  value: "Search",
  innerText: "",
  textContent: "",
  click() { searchClicks += 1; }
};
const configurableDocument = {
  body: { textContent: "Facilities Booking System Booked Available" },
  querySelectorAll(selector) {
    if (selector === "select") return configurableSelects;
    if (selector === "table tr") return [];
    if (selector === "button, input[type='button'], input[type='submit']") return [searchControl];
    return [];
  }
};
const exactFilterPayload = {
  location: "Chi Wah Learning Commons",
  booking_facility_type: "Study Room",
  date: "2026-09-23",
  submit_search: true
};
assert.equal(parser.configureSpaceAvailability(
  configurableDocument,
  { origin: "https://booking.lib.hku.hk" },
  exactFilterPayload,
  callback => callback()
).stage, "location");
assert.equal(parser.configureSpaceAvailability(
  configurableDocument,
  { origin: "https://booking.lib.hku.hk" },
  exactFilterPayload,
  callback => callback()
).stage, "facility_type");
assert.equal(parser.configureSpaceAvailability(
  configurableDocument,
  { origin: "https://booking.lib.hku.hk" },
  exactFilterPayload,
  callback => callback()
).stage, "date");
const configuredSearch = parser.configureSpaceAvailability(
  configurableDocument,
  { origin: "https://booking.lib.hku.hk" },
  exactFilterPayload,
  callback => callback()
);
assert.equal(configuredSearch.stage, "search");
assert.equal(configuredSearch.availability_search_submitted, true);
assert.equal(searchClicks, 1);
assert.equal(configurableSelects[0].value, "Chi Wah Learning Commons");
assert.equal(configurableSelects[1].value, "Study Room");
assert.equal(configurableSelects[2].value, "2026-09-23 (Wed)");
const waitingForResults = parser.configureSpaceAvailability(
  configurableDocument,
  { origin: "https://booking.lib.hku.hk" },
  { ...exactFilterPayload, submit_search: false },
  callback => callback()
);
assert.equal(waitingForResults.stage, "results_wait");
assert.equal(waitingForResults.navigation_started, true);
assert.equal(searchClicks, 1);

// Regression: the live initial ASP.NET form has three placeholder selects and
// does not populate Date until Location and Facility Type have posted back.
const initialDependentSelects = [
  filterSelect(["- Please Select -", "Main Library", "Chi Wah Learning Commons"]),
  filterSelect(["- Please Select -"]),
  filterSelect(["- Please Select -"])
];
const initialDependentDocument = {
  body: { textContent: "Facilities Booking System Booked Available" },
  querySelectorAll(selector) {
    if (selector === "select") return initialDependentSelects;
    if (selector === "label") return [];
    if (selector === "table tr") return [];
    return [];
  }
};
const initialStage = parser.configureSpaceAvailability(
  initialDependentDocument,
  { origin: "https://booking.lib.hku.hk" },
  exactFilterPayload,
  callback => callback()
);
assert.equal(initialStage.stage, "location");
assert.equal(initialDependentSelects[0].value, "Chi Wah Learning Commons");

const pageSelect = {
  options: [selectedOption("1"), { ...selectedOption("2"), selected: false }],
  selectedIndex: 0
};
const paginatedDocument = {
  body: spaceDocument.body,
  querySelectorAll(selector) {
    if (selector === "table tr") return [headerRow, availableRow, bookedRow];
    if (selector === "select") return [...bookingSelects, pageSelect];
    return [];
  }
};
const paginatedSpaces = parser.parseSpaceAvailability(paginatedDocument, {
  origin: "https://booking.lib.hku.hk",
  pathname: "/Secure/FacilityStatusDate.aspx"
});
assert.equal(paginatedSpaces.page_count, 2);
assert.equal(paginatedSpaces.result_set_complete, false);
assert.equal(paginatedSpaces.diagnostics.result_set_complete, false);

const fullyBookedDocument = {
  body: { textContent: "Facilities Booking System 2026-09-20 Booked Available" },
  querySelectorAll(selector) {
    if (selector === "table tr") return [headerRow, bookedRow];
    if (selector === "select") return bookingSelects;
    return [];
  }
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

const hoursHeader = row([cell("Library"), cell("Mon 21 Sep"), cell("Tue 22 Sep")]);
const mainHours = row([cell("Main Library"), cell("8:30 am - 11:00 pm"), cell("Closed")]);
const library24Hours = row([cell("Library 24"), cell("24 hours"), cell("24 hours")]);
const hoursDocument = {
  body: { textContent: "HKUL Opening Hours Current Hours" },
  querySelectorAll(selector) { return selector === "table tr" ? [hoursHeader, mainHours, library24Hours] : []; }
};
const hours = parser.parseHoursAndLocations(hoursDocument, {
  origin: "https://lib.hku.hk",
  pathname: "/general/hours/"
});
assert.equal(hours.location_count, 2);
assert.equal(hours.hours_available, true);
assert.equal(hours.locations[0].periods[0].status, "open");
assert.equal(hours.locations[0].periods[1].status, "closed");
assert.equal(hours.locations[1].periods[0].hours_label, "24 hours");
assert.equal(hours.diagnostics.duplicate_location_candidate_count, 0);

const unavailableHours = parser.parseHoursAndLocations({
  body: { textContent: "Opening Hours The opening hours of the selected date is not available yet." },
  querySelectorAll(selector) { return selector === "table tr" ? [hoursHeader, row([cell("Main Library"), cell("-----"), cell("-----")])] : []; }
}, {
  origin: "https://lib.hku.hk",
  pathname: "/general/hours/"
});
assert.equal(unavailableHours.hours_available, false);
assert.equal(unavailableHours.diagnostics.empty_state_found, true);
assert.equal(unavailableHours.diagnostics.placeholder_location_count, 1);

console.log("HKU Library parser synthetic tests passed.");
