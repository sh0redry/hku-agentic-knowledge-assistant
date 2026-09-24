"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const parser = require("../browser_runtime/extension/library_parser.js");
const { matchesBookingConfirmation } = require("../browser_runtime/extension/library_confirm_main.js");

const exactConfirmationTarget = {
  booking_facility_type: "Discussion Room",
  room: "Discussion Room 18",
  date: "2026-09-25",
  start_time: "10:00",
  end_time: "11:00"
};
const exactConfirmationText = "Please confirm the following booking.\nFacility Type : Discussion Room\nFacility : Discussion Room 18\nDate : 2026-09-25 (Fri)\nSession : 10:00 - 11:00";
assert.equal(matchesBookingConfirmation(exactConfirmationText, exactConfirmationTarget), true);
assert.equal(matchesBookingConfirmation(exactConfirmationText.replace("Discussion Room 18", "Discussion Room 19"), exactConfirmationTarget), false);
assert.equal(matchesBookingConfirmation(exactConfirmationText.replace("2026-09-25", "2026-09-26"), exactConfirmationTarget), false);
assert.equal(matchesBookingConfirmation(exactConfirmationText.replace("10:00 - 11:00", "11:00 - 12:00"), exactConfirmationTarget), false);
assert.equal(matchesBookingConfirmation("Are you sure?", exactConfirmationTarget), false);

const confirmDocumentListeners = new Map();
const confirmWindowListeners = new Map();
const confirmDocument = {
  addEventListener(name, callback) { confirmDocumentListeners.set(name, callback); },
  dispatchEvent(event) { confirmDocumentListeners.get(event.type)?.(event); return true; }
};
const confirmWindow = {
  document: confirmDocument,
  confirm() { throw new Error("Native confirmation must not be called by this exact-match handler test."); },
  addEventListener(name, callback) { confirmWindowListeners.set(name, callback); },
  removeEventListener(name) { confirmWindowListeners.delete(name); },
  dispatchEvent(event) { confirmWindowListeners.get(event.type)?.(event); return true; },
  setTimeout() { return 1; },
  clearTimeout() {},
  CustomEvent: class CustomEvent { constructor(type, options) { this.type = type; this.detail = options?.detail; } }
};
const nativeConfirm = confirmWindow.confirm;
vm.runInNewContext(fs.readFileSync(require.resolve("../browser_runtime/extension/library_confirm_main.js"), "utf8"), confirmWindow);
let confirmArmed = null;
let confirmResult = null;
confirmWindow.addEventListener("hku-agents:exact-library-confirm-armed-v1", event => { confirmArmed = JSON.parse(event.detail); });
confirmWindow.addEventListener("hku-agents:exact-library-confirm-result-v1", event => { confirmResult = JSON.parse(event.detail); });
confirmDocument.dispatchEvent(new confirmWindow.CustomEvent("hku-agents:arm-exact-library-confirm-v1", {
  detail: JSON.stringify(exactConfirmationTarget)
}));
assert.equal(confirmArmed.armed, true);
assert.equal(confirmWindow.confirm(exactConfirmationText), true);
assert.deepEqual(confirmResult, { dialog_seen: true, accepted: true });
assert.equal(confirmWindow.confirm === nativeConfirm, true);
confirmArmed = null;
confirmResult = null;
confirmDocument.dispatchEvent(new confirmWindow.CustomEvent("hku-agents:arm-exact-library-confirm-v1", {
  detail: JSON.stringify(exactConfirmationTarget)
}));
assert.equal(confirmArmed.armed, true);
assert.equal(confirmWindow.confirm(exactConfirmationText.replace("Discussion Room 18", "Discussion Room 19")), false);
assert.deepEqual(confirmResult, { dialog_seen: true, accepted: false });
assert.equal(confirmWindow.confirm === nativeConfirm, true);

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
  status: "available",
  page_number: 1
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
let pageChangeCount = 0;
pageSelect.value = "1";
pageSelect.dispatchEvent = (event) => { if (event.type === "change") pageChangeCount += 1; };
const selectedPage = parser.selectSpaceResultPage(paginatedDocument, {
  origin: "https://booking.lib.hku.hk",
  pathname: "/Secure/FacilityStatusDate.aspx"
}, { page_number: 2 });
assert.equal(selectedPage.navigation_started, true);
assert.equal(pageSelect.value, "2");
assert.equal(pageChangeCount, 1);
assert.throws(
  () => parser.selectSpaceResultPage(paginatedDocument, {
    origin: "https://booking.lib.hku.hk", pathname: "/Secure/FacilityStatusDate.aspx"
  }, { page_number: 3 }),
  error => error.code === "LIBRARY_SPACE_RESULT_PAGE_UNAVAILABLE"
);
assert.notEqual(paginatedSpaces.diagnostics.matrix_signature, "");

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
assert.equal(fullyBooked.diagnostics.facility_row_count, 1);
assert.equal(fullyBooked.diagnostics.status_cell_count, 1);
assert.equal(fullyBooked.diagnostics.unclassified_status_cell_count, 0);
assert.equal(fullyBooked.diagnostics.verified_empty_result_found, false);
assert.equal(fullyBooked.diagnostics.incomplete_available_slot_candidate_count, 0);

const unknownStatusRow = row([cell("4/F"), cell("Room 999"), cell("", "rgb(255, 255, 255)")]);
const unknownStatusDocument = {
  body: { textContent: "Facilities Booking System 2026-09-20 Booked Available" },
  querySelectorAll(selector) {
    if (selector === "table tr") return [headerRow, unknownStatusRow];
    if (selector === "select") return bookingSelects;
    return [];
  }
};
const unknownStatus = parser.parseSpaceAvailability(unknownStatusDocument, {
  origin: "https://booking.lib.hku.hk",
  pathname: "/FView.aspx"
});
assert.equal(unknownStatus.diagnostics.facility_row_count, 1);
assert.equal(unknownStatus.diagnostics.status_cell_count, 1);
assert.equal(unknownStatus.diagnostics.slot_candidate_count, 0);
assert.equal(unknownStatus.diagnostics.unclassified_status_cell_count, 0);
assert.equal(unknownStatus.diagnostics.neutral_nonselectable_cell_count, 1);

const ambiguousStatusRow = row([cell("4/F"), cell("Room 998"), cell("", "rgb(120, 80, 180)")]);
const ambiguousStatus = parser.parseSpaceAvailability({
  body: unknownStatusDocument.body,
  querySelectorAll(selector) {
    if (selector === "table tr") return [headerRow, ambiguousStatusRow];
    if (selector === "select") return bookingSelects;
    return [];
  }
}, { origin: "https://booking.lib.hku.hk", pathname: "/FView.aspx" });
assert.equal(ambiguousStatus.diagnostics.unclassified_status_cell_count, 1);
assert.deepEqual(ambiguousStatus.diagnostics.unclassified_cell_shapes, [{
  row_index: 1,
  column_index: 2,
  text_present: false,
  interactive: false,
  color_family: "other",
  colspan: 1
}]);

function paintedChildRow(childColors) {
  const statusCell = cell("", "rgba(0, 0, 0, 0)");
  statusCell.querySelectorAll = () => childColors.map((color) => cell("", color));
  statusCell.querySelector = () => null;
  return row([cell("4/F"), cell("Room 997"), statusCell]);
}
function documentWithStatusRow(statusRow) {
  return {
    body: unknownStatusDocument.body,
    querySelectorAll(selector) {
      if (selector === "table tr") return [headerRow, statusRow];
      if (selector === "select") return bookingSelects;
      return [];
    }
  };
}
const innerPainted = parser.parseSpaceAvailability(
  documentWithStatusRow(paintedChildRow(["rgb(91, 159, 11)"])),
  { origin: "https://booking.lib.hku.hk", pathname: "/FView.aspx" }
);
assert.equal(innerPainted.available_slot_count, 1);
assert.equal(innerPainted.diagnostics.unclassified_status_cell_count, 0);
const conflictingPaint = parser.parseSpaceAvailability(
  documentWithStatusRow(paintedChildRow(["rgb(91, 159, 11)", "rgb(227, 99, 99)"])),
  { origin: "https://booking.lib.hku.hk", pathname: "/FView.aspx" }
);
assert.equal(conflictingPaint.available_slot_count, 0);
assert.equal(conflictingPaint.diagnostics.unclassified_status_cell_count, 1);
const mixedParentChild = paintedChildRow(["rgb(91, 159, 11)"]);
mixedParentChild.querySelectorAll("th, td")[2].style.backgroundColor = "rgb(227, 99, 99)";
const conflictingParentPaint = parser.parseSpaceAvailability(
  documentWithStatusRow(mixedParentChild),
  { origin: "https://booking.lib.hku.hk", pathname: "/FView.aspx" }
);
assert.equal(conflictingParentPaint.available_slot_count, 0);
assert.equal(conflictingParentPaint.diagnostics.unclassified_status_cell_count, 1);
const inheritedPaintCell = cell("", "rgba(0, 0, 0, 0)");
const inheritedPaintRow = {
  tagName: "TR",
  style: { backgroundColor: "rgb(91, 159, 11)" },
  querySelectorAll() { return [cell("4/F"), cell("Room 996"), inheritedPaintCell]; }
};
inheritedPaintCell.parentElement = inheritedPaintRow;
const inheritedPaint = parser.parseSpaceAvailability({
  body: unknownStatusDocument.body,
  querySelectorAll(selector) {
    if (selector === "table tr") return [headerRow, inheritedPaintRow];
    if (selector === "select") return bookingSelects;
    return [];
  }
}, { origin: "https://booking.lib.hku.hk", pathname: "/FView.aspx" });
assert.equal(inheritedPaint.available_slot_count, 1);
assert.equal(inheritedPaint.diagnostics.unclassified_status_cell_count, 0);
const transparentNeutral = parser.parseSpaceAvailability({
  body: unknownStatusDocument.body,
  querySelectorAll(selector) {
    if (selector === "table tr") return [headerRow, row([cell("4/F"), cell("Room 995"), cell("", "rgba(0, 0, 0, 0)")])];
    if (selector === "select") return bookingSelects;
    return [];
  }
}, { origin: "https://booking.lib.hku.hk", pathname: "/FView.aspx" });
assert.equal(transparentNeutral.diagnostics.unclassified_status_cell_count, 0);
assert.equal(transparentNeutral.diagnostics.neutral_nonselectable_cell_count, 1);

const explicitEmptyDocument = {
  body: { textContent: "Facilities Booking System 2026-09-20 Booked Available No facilities found" },
  querySelectorAll(selector) {
    if (selector === "table tr") return [headerRow];
    if (selector === "select") return bookingSelects;
    return [];
  }
};
const explicitEmpty = parser.parseSpaceAvailability(explicitEmptyDocument, {
  origin: "https://booking.lib.hku.hk",
  pathname: "/FView.aspx"
});
assert.equal(explicitEmpty.diagnostics.verified_empty_result_found, true);
assert.equal(explicitEmpty.diagnostics.slot_candidate_count, 0);

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

const bookingTarget = {
  location: "Main Library",
  floor: "4/F",
  booking_facility_type: "Single Study Room (3 sessions)",
  room: "Single Study Room (3 sessions) Room 424",
  date: "2026-09-23",
  start_time: "13:00",
  end_time: "17:00"
};
function labeledSelect(id, label, values, selectedIndex = 0) {
  const select = filterSelect(values, selectedIndex);
  select.id = id;
  select.closest = () => ({ querySelectorAll: () => [cell(label)] });
  return select;
}
const bookingSelectsForForm = [
  labeledSelect("location", "Location", ["Chi Wah Learning Commons", "Main Library"]),
  labeledSelect("floor", "Floor", ["3/F", "4/F"]),
  labeledSelect("facilityType", "Facility Type", ["Study Room", "Single Study Room (3 sessions)"]),
  labeledSelect("facility", "Facility", ["Room 422", bookingTarget.room]),
  labeledSelect("date", "Date", ["2026-09-22 (Tue)", "2026-09-23 (Wed)"])
];
const bookingCheckboxRow = { innerText: "13:00 - 17:00" };
let bookingCheckboxChanges = 0;
const bookingCheckbox = {
  checked: false,
  disabled: false,
  value: "13:00 - 17:00",
  closest: () => bookingCheckboxRow,
  dispatchEvent() { bookingCheckboxChanges += 1; },
  ownerDocument: { defaultView: { Event: class Event {} } }
};
let bookingSubmitClicks = 0;
const bookingSubmit = {
  innerText: "Submit",
  disabled: false,
  click() { bookingSubmitClicks += 1; }
};
const bookingFormDocument = {
  body: { innerText: "New Booking" },
  querySelectorAll(selector) {
    if (selector === "select") return bookingSelectsForForm;
    if (selector === "input[type='checkbox']") return [bookingCheckbox];
    if (selector === "button, input[type='submit'], input[type='button']") return [bookingSubmit];
    if (selector === "label") return [];
    return [];
  }
};
const bookingLocation = {
  origin: "https://booking.lib.hku.hk",
  href: "https://booking.lib.hku.hk/Secure/NewBooking.aspx",
  pathname: "/Secure/NewBooking.aspx"
};
assert.equal(parser.inspectBookingForm(bookingFormDocument, bookingLocation, bookingTarget).ready_to_submit, false);
const configuredBookingForm = parser.configureBookingForm(bookingFormDocument, bookingLocation, bookingTarget);
assert.equal(configuredBookingForm.ready_to_submit, true);
assert.equal(configuredBookingForm.policy_notice_found, false);
assert.equal(configuredBookingForm.session.exact_session_selected, true);
assert.equal(configuredBookingForm.session.other_selected_session_count, 0);
assert.equal(bookingCheckboxChanges, 2);
assert.deepEqual(bookingSelectsForForm.map((select) => select.value), [
  "Main Library", "4/F", "Single Study Room (3 sessions)", bookingTarget.room, "2026-09-23 (Wed)"
]);
assert.throws(
  () => parser.submitBookingOnce(bookingFormDocument, bookingLocation, bookingTarget, false),
  error => error.code === "LIBRARY_POLICY_ACK_REQUIRED"
);
assert.equal(bookingSubmitClicks, 0);
assert.deepEqual(parser.submitBookingOnce(bookingFormDocument, bookingLocation, bookingTarget, true), {
  submit_click_dispatched: true,
  submit_button_candidate_count: 1
});
assert.equal(bookingSubmitClicks, 1);
assert.throws(
  () => parser.submitBookingOnce(bookingFormDocument, bookingLocation, { ...bookingTarget, date: "2026-09-24" }, true),
  error => error.code === "LIBRARY_BOOKING_FORM_MISMATCH"
);
assert.equal(bookingSubmitClicks, 1);

const discussionBookingTarget = {
  location: "Main Library",
  floor: "Level 3",
  booking_facility_type: "Discussion Room",
  room: "Discussion Room 2",
  date: "2026-09-25",
  start_time: "10:00",
  end_time: "11:00"
};
const discussionSelects = [
  labeledSelect("location", "Location", ["Main Library"]),
  labeledSelect("floor", "Floor", ["Level 3"]),
  labeledSelect("facilityType", "Facility Type", ["Discussion Room"]),
  labeledSelect("facility", "Facility", ["Discussion Room 2"]),
  labeledSelect("date", "Date", ["2026-09-25 (Fri)"])
];
const discussionCheckboxRow = { innerText: "10:00 - 11:00" };
const discussionCheckbox = {
  checked: false,
  disabled: false,
  value: "10:00 - 11:00",
  closest: () => discussionCheckboxRow,
  dispatchEvent() {},
  ownerDocument: { defaultView: { Event: class Event {} } }
};
let discussionSubmitClicks = 0;
const discussionSubmit = { innerText: "Submit", disabled: false, click() { discussionSubmitClicks += 1; } };
const discussionBookingFormDocument = {
  body: { innerText: "New Booking" },
  querySelectorAll(selector) {
    if (selector === "select") return discussionSelects;
    if (selector === "input[type='checkbox']") return [discussionCheckbox];
    if (selector === "button, input[type='submit'], input[type='button']") return [discussionSubmit];
    if (selector === "label") return [];
    return [];
  }
};
assert.equal(parser.configureBookingForm(discussionBookingFormDocument, bookingLocation, discussionBookingTarget).ready_to_submit, true);
assert.equal(parser.submitBookingOnce(discussionBookingFormDocument, bookingLocation, discussionBookingTarget, true).submit_click_dispatched, true);
assert.equal(discussionSubmitClicks, 1);

let yesClicks = 0;
const confirmationText = "Submit Booking Please confirm the following booking. Facility Type : Discussion Room Facility : Discussion Room 2 Date : 2026-09-25 (Fri) Session : 10:00 - 11:00 Yes No";
const confirmationDialog = {
  innerText: confirmationText,
  getAttribute() { return null; }
};
const yesButton = {
  id: "main_btnSubmitYes", type: "submit", value: "Yes", disabled: false,
  parentElement: confirmationDialog,
  getAttribute(name) { return name === "name" ? "ctl00$main$btnSubmitYes" : null; },
  getClientRects() { return [{}]; },
  click() { yesClicks += 1; }
};
const confirmationDocument = { querySelectorAll(selector) { return selector === "input#main_btnSubmitYes" ? [yesButton] : []; } };
assert.equal(parser.bookingConfirmationDialog(confirmationDocument, bookingLocation, discussionBookingTarget).ready_to_confirm, true);
assert.throws(
  () => parser.acceptExactBookingConfirmation(confirmationDocument, bookingLocation, { ...discussionBookingTarget, room: "Discussion Room 3" }),
  error => error.code === "LIBRARY_BOOKING_CONFIRMATION_MISMATCH"
);
assert.equal(yesClicks, 0);
assert.equal(parser.acceptExactBookingConfirmation(confirmationDocument, bookingLocation, discussionBookingTarget).confirmation_yes_click_dispatched, true);
assert.equal(yesClicks, 1);
yesButton.getClientRects = () => [];
assert.equal(parser.bookingConfirmationDialog(confirmationDocument, bookingLocation, discussionBookingTarget).ready_to_confirm, undefined);
yesButton.getClientRects = () => [{}];
assert.throws(
  () => parser.submitBookingOnce(discussionBookingFormDocument, bookingLocation, { ...discussionBookingTarget, end_time: "12:00" }, true),
  error => error.code === "LIBRARY_BOOKING_FORM_MISMATCH"
);
assert.equal(discussionSubmitClicks, 1);

let bookingRecordLinkClicks = 0;
const bookingRecordLink = {
  innerText: "My Booking Record",
  getAttribute(name) { return name === "href" ? "/Secure/BookingRecord.aspx" : null; },
  click() { bookingRecordLinkClicks += 1; }
};
assert.deepEqual(parser.openBookingRecord({ querySelectorAll: selector => selector === "a" ? [bookingRecordLink] : [] }, bookingLocation), {
  navigation_started: true
});
assert.equal(bookingRecordLinkClicks, 1);
const exactRecordText = "2026-09-23 4/F Single Study Room (3 sessions) Room 424 13:00 17:00";
const recordLocation = { ...bookingLocation, pathname: "/Secure/BookingRecord.aspx" };
const bookingRecord = parser.verifyBookingRecord({
  body: { innerText: "My Booking Record" },
  querySelectorAll(selector) {
    if (selector !== "table tr") return [];
    return [
      { innerText: exactRecordText },
      { innerText: `${exactRecordText} Cancelled` }
    ];
  }
}, recordLocation, bookingTarget);
assert.equal(bookingRecord.record_page_marker_found, true);
assert.equal(bookingRecord.exact_target_match_count, 1);
assert.equal(bookingRecord.verified_exactly_once, true);
const duplicateBookingRecord = parser.verifyBookingRecord({
  body: { innerText: "My Booking Record" },
  querySelectorAll(selector) {
    return selector === "table tr"
      ? [{ innerText: exactRecordText }, { innerText: exactRecordText }]
      : [];
  }
}, recordLocation, bookingTarget);
assert.equal(duplicateBookingRecord.exact_target_match_count, 2);
assert.equal(duplicateBookingRecord.verified_exactly_once, false);
assert.equal(parser.verifyBookingRecord({
  body: { innerText: "New Booking My Booking Record" },
  querySelectorAll(selector) { return selector === "table tr" ? [{ innerText: exactRecordText }] : []; }
}, bookingLocation, bookingTarget).verified_exactly_once, false);

console.log("HKU Library parser synthetic tests passed.");
