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
const bookingCommands = [];
let bookingPhase = "form";
let storedBookingAttempts = [];
let loginTransitionReads = 0;
let recordLoadingReads = 0;
let recordLoginFailures = 0;
let recoveryNavigations = 0;
let tabUrl = "https://booking.lib.hku.hk/Secure/FacilityStatusDate.aspx";
const dateParts = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit", day: "2-digit"
}).formatToParts(new Date());
const datePart = (type) => dateParts.find((item) => item.type === type).value;
const today = `${datePart("year")}-${datePart("month")}-${datePart("day")}`;

function snapshot(page) {
  const discussion = activeFacilityType === "Discussion Room";
  const room = discussion
    ? `Discussion Room ${page}`
    : (page === 1 ? "Room 101" : "Room 102");
  const pageCount = discussion ? 1 : 2;
  const complete = discussion || page === 2;
  return {
    origin: "https://booking.lib.hku.hk",
    logged_in: true,
    page_kind: "space_availability",
    location: activeLocation,
    booking_facility_type: activeFacilityType,
    date: today,
    source_last_updated_at: null,
    page_number: page,
    page_count: pageCount,
    result_set_complete: complete,
    available_slot_count: 1,
    available_slots: [{
      floor: discussion ? "Level 3" : "4/F",
      room,
      start_time: discussion ? "13:00" : "13:00",
      end_time: discussion ? "14:00" : "17:00",
      status: "available"
    }],
    diagnostics: {
      parser_version: "0.3.6",
      availability_marker_found: true,
      availability_legend_found: true,
      booked_legend_found: true,
      table_matrix_found: true,
      matrix_signature: page === 1 ? "11111111" : "22222222",
      selected_filters_found: true,
      result_set_complete: complete,
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
    alarms: { create() {}, async clear() {}, onAlarm: { addListener() {} } },
    storage: { local: {
      async get(defaults) { return { ...defaults, pairingToken: "", bridgePort: 7860, libraryBookingAttempts: storedBookingAttempts }; },
      async set(value) { if (value.libraryBookingAttempts) storedBookingAttempts = value.libraryBookingAttempts; }
    } },
    runtime: {
      onMessage: { addListener() {} },
      onStartup: { addListener() {} },
      onInstalled: { addListener() {} }
    },
    tabs: {
      async create() { openedTabs += 1; return { id: 42 }; },
      async get(tabId) { return { id: tabId, url: tabUrl, status: "complete" }; },
      async update(tabId, options) { recoveryNavigations += 1; tabUrl = options.url; return { id: tabId }; },
      async sendMessage(_tabId, message) {
        bookingCommands.push(message.command);
        if (message.command === "library.spaces.inspect_booking_form") {
          return { ok: true, data: { ready_to_submit: true, submit_button_candidate_count: 1 } };
        }
        if (message.command === "library.spaces.submit_booking_once") {
          bookingPhase = "dialog";
          return { ok: true, data: { submit_click_dispatched: true, submit_button_candidate_count: 1,
            confirmation_dialog_seen: false, confirmation_dialog_accepted: false } };
        }
        if (message.command === "library.spaces.inspect_booking_confirmation") {
          return { ok: true, data: { dialog_found: bookingPhase === "dialog", ready_to_confirm: bookingPhase === "dialog" } };
        }
        if (message.command === "library.spaces.accept_booking_confirmation") {
          bookingPhase = "record";
          return { ok: true, data: { confirmation_yes_click_dispatched: true, exact_target_matched: true } };
        }
        if (message.command === "library.spaces.read_booking_record") {
          if (message.payload?.fresh_default_record_navigation !== undefined) {
            assert.equal(message.payload.fresh_default_record_navigation, true);
          }
          const loading = recordLoadingReads > 0;
          if (loading) recordLoadingReads -= 1;
          return { ok: true, data: { record_page_marker_found: bookingPhase === "record",
            exact_target_match_count: bookingPhase === "record" ? 1 : 0,
            verified_exactly_once: bookingPhase === "record", diagnostics: { record_loading_found: loading } } };
        }
        if (message.command === "library.spaces.open_booking_record") {
          if (recordLoginFailures > 0) {
            recordLoginFailures -= 1;
            tabUrl = "https://lib.hku.hk/hkulauth/";
            return { ok: false, error: { code: "LIBRARY_LOGIN_REQUIRED", message: "Session timed out" } };
          }
          bookingPhase = "record";
          return { ok: true, data: { navigation_started: true, default_record_route: true } };
        }
        if (message.command === "library.spaces.configure_availability") {
          if (loginTransitionReads > 0) {
            loginTransitionReads -= 1;
            tabUrl = "https://lib.hku.hk/";
            return { ok: false, error: { code: "WRONG_LIBRARY_SPACE_PAGE", message: "Login redirect" } };
          }
          tabUrl = "https://booking.lib.hku.hk/Secure/FacilityStatusDate.aspx";
          if (message.payload.inspect_dates_only) {
            return { ok: true, data: {
              navigation_started: false, stage: "date_options_ready",
              location: message.payload.location,
              booking_facility_type: message.payload.booking_facility_type,
              offered_dates: [today], availability_search_submitted: false
            } };
          }
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
        if (message.command === "library.spaces.select_exact_slot") {
          return { ok: true, data: { slot_selection_performed: true, candidate_count: 1 } };
        }
        if (message.command === "library.spaces.configure_booking_form") {
          return { ok: true, data: {
            ready_to_submit: true,
            policy_notice_found: false,
            selected_fields: { facility: message.payload.target.room },
            session: { start_time: message.payload.target.start_time, end_time: message.payload.target.end_time },
            submit_button_candidate_count: 1
          } };
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
  invalid.setUTCDate(invalid.getUTCDate() + 15);
  await assert.rejects(
    vm.runInContext(`searchLibrarySpaceAvailability({facility_type:"single_study_room",date:"${invalid.toISOString().slice(0, 10)}"})`, context),
    error => error.code === "LIBRARY_SPACE_DATE_OUT_OF_WINDOW"
  );
  assert.equal(openedTabs, 0);
  loginTransitionReads = 2;
  const dateOptions = await vm.runInContext('listLibrarySpaceDates({facility_type:"study_room"})', context);
  assert.equal(loginTransitionReads, 0);
  assert.equal(dateOptions.location, "Chi Wah Learning Commons");
  assert.deepEqual([...dateOptions.offered_dates], [today]);
  assert.equal(dateOptions.availability_search_submitted, false);
  assert.equal(openedTabs, 1);
  const refreshedDates = await vm.runInContext('listLibrarySpaceDates({facility_type:"study_room"})', context);
  assert.equal(refreshedDates.availability_search_submitted, false);
  assert.equal(openedTabs, 1, "date polling must reuse its own availability tab");
  await assert.rejects(
    vm.runInContext(`bookLibrarySpaceExactlyOnce({operation:"prepare",facility_type:"discussion_room",target:{facility_type:"discussion_room",date:"${today}",floor:"Level 3",room:"Discussion Room 1",start_time:"13:00",end_time:"14:00"}})`, context),
    error => error.code === "LIBRARY_DISCUSSION_ROOM_RULES_ACK_REQUIRED"
  );
  await assert.rejects(
    vm.runInContext(`submitPreparedLibraryBooking({target:{facility_type:"discussion_room"}})`, context),
    error => error.code === "LIBRARY_DISCUSSION_ROOM_RULES_ACK_REQUIRED"
  );
  assert.equal(openedTabs, 1);

  tabUrl = "https://example.com/";
  await assert.rejects(
    vm.runInContext('librarySpaceNavigationError(42, commandError("WRONG_LIBRARY_SPACE_PAGE", "wrong"))', context),
    error => error.code === "WRONG_LIBRARY_SPACE_PAGE"
  );
  loginTransitionReads = 1;
  const discussionPreparation = await vm.runInContext(`bookLibrarySpaceExactlyOnce({
    operation:"prepare",
    facility_type:"discussion_room",
    discussion_room_rules_acknowledged:true,
    target:{facility_type:"discussion_room",location:"Main Library",booking_facility_type:"Discussion Room",date:"${today}",floor:"Level 3",room:"Discussion Room 1",start_time:"13:00",end_time:"14:00"}
  })`, context);
  assert.equal(discussionPreparation.ready_to_submit, true);
  assert.equal(discussionPreparation.slot_selection_performed, true);
  assert.equal(discussionPreparation.booking_writes_performed, 0);
  assert.equal(openedTabs, 2);

  const result = await vm.runInContext(`searchLibrarySpaceAvailability({facility_type:"single_study_room",date:"${today}"})`, context);
  assert.equal(openedTabs, 3);
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
  assert.equal(configuredTargets.length, additionalRoutes.length + 2);
  const bookingResult = await vm.runInContext(`submitPreparedLibraryBooking({
    execution_id:"11111111-1111-4111-8111-111111111111",prepared_tab_id:42,policy_acceptance_acknowledged:true,
    discussion_room_rules_acknowledged:true,
    target:{facility_type:"discussion_room",location:"Main Library",booking_facility_type:"Discussion Room",
      date:"${today}",floor:"Level 3",room:"Discussion Room 1",start_time:"13:00",end_time:"14:00"}
  })`, context);
  assert.equal(bookingResult.outcome, "confirmed");
  assert.equal(bookingCommands.filter((command) => command === "library.spaces.accept_booking_confirmation").length, 1);
  assert.equal(bookingCommands.includes("library.spaces.open_booking_record"), false);
  const submitsBeforeExpiry = bookingCommands.filter(command => command === "library.spaces.submit_booking_once").length;
  await assert.rejects(vm.runInContext(`submitPreparedLibraryBooking({
    execution_id:"22222222-2222-4222-8222-222222222222",prepared_tab_id:42,policy_acceptance_acknowledged:true,
    discussion_room_rules_acknowledged:true,not_after:"2000-01-01T00:00:00+08:00",
    target:{facility_type:"discussion_room",location:"Main Library",booking_facility_type:"Discussion Room",
      date:"${today}",floor:"Level 3",room:"Discussion Room 1",start_time:"13:00",end_time:"14:00"}
  })`, context), error => error.code === "EXECUTION_WINDOW_EXPIRED");
  assert.equal(bookingCommands.filter(command => command === "library.spaces.submit_booking_once").length, submitsBeforeExpiry);
  recordLoginFailures = 5;
  const recoveryBefore = recoveryNavigations;
  const recoveredRecord = await vm.runInContext(`readExactLibraryBookingRecord({facility_type:"discussion_room",
    location:"Main Library",booking_facility_type:"Discussion Room",date:"${today}",floor:"Level 3",
    room:"Discussion Room 1",start_time:"13:00",end_time:"14:00"})`, context);
  assert.equal(recoveredRecord.record_page_marker_found, true);
  assert.equal(recoveredRecord.diagnostics.session_recovery_attempted, true);
  assert.equal(recoveredRecord.diagnostics.session_recovery_succeeded, true);
  assert.equal(recoveryNavigations - recoveryBefore, 1);
  assert.equal(bookingCommands.filter(command => command === "library.spaces.submit_booking_once").length, submitsBeforeExpiry);
  context.recoveryState = { attempted: false, startedAt: Date.now() - 3000 };
  tabUrl = "https://hkuportal.hku.hk/login";
  assert.equal(await vm.runInContext('recoverLibraryReadSession(42, {code:"LIBRARY_LOGIN_REQUIRED"}, recoveryState, Date.now()+1000)', context), false);
  assert.equal(context.recoveryState.attempted, false);
  tabUrl = "https://lib.hku.hk/hkulauth/";
  assert.equal(await vm.runInContext('recoverLibraryReadSession(42, {code:"LIBRARY_LOGIN_REQUIRED"}, recoveryState, Date.now()+1000)', context), true);
  assert.equal(await vm.runInContext('recoverLibraryReadSession(42, {code:"LIBRARY_LOGIN_REQUIRED"}, recoveryState, Date.now()+1000)', context), false);
  context.recoveryState = { attempted: false, startedAt: Date.now() - 3000 };
  assert.equal(await vm.runInContext('recoverLibraryReadSession(42, {code:"LIBRARY_LOGIN_REQUIRED"}, recoveryState, Date.now()-1)', context), false);
  recordLoadingReads = 2;
  const readsBeforeLoading = bookingCommands.filter(command => command === "library.spaces.read_booking_record").length;
  const recordCheck = await vm.runInContext(`bookLibrarySpaceExactlyOnce({operation:"record_check",
    target:{facility_type:"discussion_room",location:"Main Library",booking_facility_type:"Discussion Room",
      date:"${today}",floor:"Level 3",room:"Discussion Room 1",start_time:"13:00",end_time:"14:00"}})`, context);
  assert.equal(recordCheck.record_page_marker_found, true);
  assert.equal(bookingCommands.filter(command => command === "library.spaces.read_booking_record").length - readsBeforeLoading, 3);
  assert.equal(bookingCommands.filter(command => command === "library.spaces.submit_booking_once").length, submitsBeforeExpiry);
  await assert.rejects(vm.runInContext('readExactLibraryBookingRecord({facility_type:"study_room"})', context), error => error.code === "INVALID_INPUT");
  console.log("HKUL background date and pagination tests passed.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
