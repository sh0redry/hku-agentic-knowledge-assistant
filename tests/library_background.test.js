"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("browser_runtime/extension/background.js", "utf8");
let openedTabs = 0;
let currentPage = 1;
let pageSelections = 0;
let stalePageReads = 0;
let activeLocation = "Main Library";
let activeFacilityType = "Single Study Room (3 sessions)";
const configuredTargets = [];
const dateParts = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit", day: "2-digit"
}).formatToParts(new Date());
const datePart = (type) => dateParts.find((item) => item.type === type).value;
const today = `${datePart("year")}-${datePart("month")}-${datePart("day")}`;

function snapshot(page) {
  const room = page === 1 ? "Room 101" : "Room 102";
  return {
    origin: "https://booking.lib.hku.hk",
    logged_in: true,
    page_kind: "space_availability",
    location: activeLocation,
    booking_facility_type: activeFacilityType,
    date: today,
    source_last_updated_at: null,
    page_number: page,
    page_count: 2,
    result_set_complete: false,
    available_slot_count: 1,
    available_slots: [{ floor: "4/F", room, start_time: "13:00", end_time: "17:00", status: "available" }],
    diagnostics: {
      parser_version: "0.3.5",
      availability_marker_found: true,
      availability_legend_found: true,
      booked_legend_found: true,
      table_matrix_found: true,
      matrix_signature: page === 1 ? "11111111" : "22222222",
      selected_filters_found: true,
      result_set_complete: false,
      verified_empty_result_found: false,
      facility_row_count: 1,
      status_cell_count: 2,
      unclassified_status_cell_count: page === 2 ? 1 : 0,
      unclassified_cell_shapes: page === 2 ? [{
        row_index: 3, column_index: 7, text_present: false,
        interactive: true, color_family: "unreadable", colspan: 1
      }] : [],
      neutral_nonselectable_cell_count: page === 1 ? 1 : 0,
      slot_candidate_count: 1,
      parsed_available_slot_count: 1,
      incomplete_available_slot_candidate_count: 0
    }
  };
}

const context = {
  importScripts() {},
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  URL,
  URLSearchParams,
  Intl,
  Date,
  console,
  chrome: {
    storage: { local: { async get() { return { pairingToken: "", bridgePort: 7860 }; } } },
    runtime: {
      onMessage: { addListener() {} },
      onStartup: { addListener() {} },
      onInstalled: { addListener() {} }
    },
    tabs: {
      async create() { openedTabs += 1; return { id: 42 }; },
      async sendMessage(_tabId, message) {
        if (message.command === "library.spaces.configure_availability") {
          activeLocation = message.payload.location;
          activeFacilityType = message.payload.booking_facility_type;
          currentPage = 1;
          configuredTargets.push({
            facility_type: activeFacilityType,
            location: activeLocation,
            date: message.payload.date
          });
          return { ok: true, data: { navigation_started: false, availability_search_submitted: true } };
        }
        if (message.command === "library.spaces.select_result_page") {
          currentPage = message.payload.page_number;
          pageSelections += 1;
          return { ok: true, data: { navigation_started: true, page_number: currentPage } };
        }
        if (message.command === "library.spaces.read_availability") {
          if (currentPage === 2 && stalePageReads === 0) {
            stalePageReads += 1;
            return { ok: true, data: { ...snapshot(1), page_number: 2 } };
          }
          return { ok: true, data: snapshot(currentPage) };
        }
        throw new Error(`Unexpected command: ${message.command}`);
      }
    }
  }
};
context.self = context;
vm.createContext(context);
vm.runInContext(source, context);

(async () => {
  const invalid = new Date(`${today}T00:00:00Z`);
  invalid.setUTCDate(invalid.getUTCDate() + 2);
  await assert.rejects(
    vm.runInContext(`searchLibrarySpaceAvailability({facility_type:"single_study_room",date:"${invalid.toISOString().slice(0, 10)}"})`, context),
    error => error.code === "LIBRARY_SPACE_DATE_OUT_OF_WINDOW"
  );
  assert.equal(openedTabs, 0);
  await assert.rejects(
    vm.runInContext(`bookLibrarySpaceExactlyOnce({operation:"prepare",facility_type:"discussion_room",target:{facility_type:"discussion_room",date:"${today}",floor:"Level 3",room:"Discussion Room 1",start_time:"13:00",end_time:"14:00"}})`, context),
    error => error.code === "LIBRARY_BOOKING_FACILITY_NOT_ENABLED"
  );
  await assert.rejects(
    vm.runInContext(`submitPreparedLibraryBooking({target:{facility_type:"discussion_room"}})`, context),
    error => error.code === "LIBRARY_BOOKING_FACILITY_NOT_ENABLED"
  );
  assert.equal(openedTabs, 0);

  const result = await vm.runInContext(`searchLibrarySpaceAvailability({facility_type:"single_study_room",date:"${today}"})`, context);
  assert.equal(openedTabs, 1);
  assert.equal(pageSelections, 1);
  assert.equal(stalePageReads, 1);
  assert.equal(result.page_navigation_interactions_performed, true);
  assert.equal(result.result_pages_read, 2);
  assert.equal(result.snapshot.result_set_complete, true);
  assert.equal(result.snapshot.available_slot_count, 2);
  assert.deepEqual([...result.snapshot.available_slots.map((slot) => slot.room)], ["Room 101", "Room 102"]);
  assert.equal(result.snapshot.diagnostics.neutral_nonselectable_cell_count, 1);
  assert.equal(result.snapshot.diagnostics.unclassified_cell_shapes[0].page_number, 2);
  assert.equal(result.booking_writes_performed, 0);

  const additionalRoutes = [
    ["av_group_viewing_room", "AV Group Viewing Room"],
    ["communal_virtual_pc", "Communal Virtual PC"],
    ["computer", "Computer"],
    ["computer_in_lic", "Computer in LIC"],
    ["engraving_cutting_computer", "computer-controlled machines for engraving/cutting"],
    ["concept_and_creation_room", "Concept and Creation Room"],
    ["discussion_room", "Discussion Room"],
    ["microform_scanner", "Special Collections - Microform Scanner"],
    ["overhead_scanner", "Special Collections - Overhead Scanner"],
    ["research_desk", "Special Collections - Research Desk"],
    ["studio_editing_room", "Studio and Editing Room"],
    ["study_table", "Study Table"],
    ["study_table_deep_quiet", "Study Table (Deep Quiet)"],
    ["study_room", "Study Room"]
  ];
  for (const [facility_type, booking_facility_type] of additionalRoutes) {
    const route = await vm.runInContext(
      `searchLibrarySpaceAvailability({facility_type:${JSON.stringify(facility_type)},date:${JSON.stringify(today)}})`,
      context
    );
    assert.equal(route.booking_facility_type, booking_facility_type);
    assert.equal(route.location, facility_type === "study_room" ? "Chi Wah Learning Commons" : "Main Library");
    assert.equal(route.snapshot.result_set_complete, true);
    assert.equal(route.booking_writes_performed, 0);
  }
  assert.equal(configuredTargets.length, additionalRoutes.length + 1);
  console.log("HKUL background date and pagination tests passed.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
