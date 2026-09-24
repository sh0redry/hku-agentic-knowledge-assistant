"use strict";

importScripts("connection_lifecycle.js", "browser_targets.js");

const SIS_URL_PATTERN = "https://sis-main.hku.hk/*";
const WEEKLY_TIMETABLE_URL_PATTERN = "https://sweb.hku.hk/*";
const MOODLE_URL_PATTERN = "https://moodle.hku.hk/*";
const LIBRARY_RESEARCH_URL_PATTERN = "https://julac-hku.primo.exlibrisgroup.com/*";
const LIBRARY_BOOKING_URL_PATTERNS = ["https://booking.lib.hku.hk/*", "https://lib.hku.hk/hkulauth/*"];
const PORTAL_URL_PATTERNS = [
  "https://hkuportal.hku.hk/*",
  "https://studentportal.hku.hk/*"
];
const SIS_ORIGIN = "https://sis-main.hku.hk";
const WEEKLY_TIMETABLE_ORIGIN = "https://sweb.hku.hk";
const MOODLE_ORIGIN = "https://moodle.hku.hk";
const PORTAL_ORIGINS = new Set([
  "https://hkuportal.hku.hk",
  "https://studentportal.hku.hk"
]);
const ALLOWED_COMMANDS = new Set([
  "browser.health",
  "hku.bind_tab",
  "hku.inspect_portal",
  "hku.open_sis",
  "hku.open_enrollment_add_classes",
  "hku.open_weekly_timetable",
  "hku.open_moodle",
  "portal.list_notices",
  "sis.bind_tab",
  "sis.inspect_page",
  "sis.inspect_cart",
  "sis.open_enrollment_add_classes",
  "sis.select_term",
  "sis.preflight",
  "sis.get_status",
  "timetable.inspect_weekly",
  "moodle.inspect_dashboard",
  "moodle.open_dashboard",
  "moodle.list_courses",
  "moodle.list_upcoming_assignments",
  "library.research.search",
  "library.research.item",
  "library.research.access_options",
  "library.hours_and_locations",
  "library.spaces.search_availability",
  "library.spaces.book_exact_once"
]);
const NAVIGATION_DEADLINE_MS = 30000;
// Keep the persistent anti-replay ledger below Chrome's local storage quota.
// Entries are never evicted: a full ledger fails closed.
const MAX_RECORDED_BOOKING_ATTEMPTS = 10000;

let socket = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let boundTabId = null;
let lastSnapshot = null;
let targetRegistry = [];
let bridgeStatus = "not_configured";
let reconnectAttempt = 0;
let nextRetryAt = 0;
let lastConnectionError = null;
let connectionGeneration = 0;

async function loadSettings() {
  return chrome.storage.local.get({
    pairingToken: "",
    bridgePort: 7860
  });
}

function websocketUrl(port) {
  return `ws://127.0.0.1:${Number(port)}/api/v1/browser/ws`;
}

function publicTabState() {
  if (!lastSnapshot) {
    return {
      bound: boundTabId !== null,
      origin: null,
      logged_in: null,
      page_kind: "unknown",
      term_label: null,
      course_count: 0
    };
  }
  return {
    bound: boundTabId !== null,
    origin: lastSnapshot.origin || null,
    logged_in: lastSnapshot.logged_in ?? null,
    page_kind: lastSnapshot.page_kind || "unknown",
    term_label: lastSnapshot.term_label || null,
    course_count: Number(lastSnapshot.course_count || 0),
    temporary_course_count: Number(lastSnapshot.temporary_course_count || 0),
    schedule_course_count: Number(lastSnapshot.schedule_course_count || 0)
  };
}

async function refreshTargetRegistry() {
  const tabs = await chrome.tabs.query({ url: self.HKUBrowserTargets.targetPatterns() });
  targetRegistry = self.HKUBrowserTargets.buildRegistry(tabs, boundTabId, lastSnapshot);
  return targetRegistry;
}

async function sendHeartbeat() {
  if (socket && socket.readyState === WebSocket.OPEN && bridgeStatus === "paired") {
    try {
      await refreshTargetRegistry();
    } catch (_error) {
      // Fail closed for discovery while keeping the existing command channel alive.
      targetRegistry = [];
    }
    if (socket && socket.readyState === WebSocket.OPEN && bridgeStatus === "paired") {
      socket.send(JSON.stringify({
        type: "heartbeat",
        tab: publicTabState(),
        targets: targetRegistry
      }));
    }
  }
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectAttempt += 1;
  const delayMs = self.HKUConnectionLifecycle.reconnectDelayMs(reconnectAttempt);
  nextRetryAt = Date.now() + delayMs;
  reconnectTimer = setTimeout(() => connect(), delayMs);
}

function restartConnection() {
  clearTimeout(reconnectTimer);
  reconnectAttempt = 0;
  nextRetryAt = 0;
  lastConnectionError = null;
  connectionGeneration += 1;
  const previousSocket = socket;
  socket = null;
  if (previousSocket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(previousSocket.readyState)) {
    try {
      previousSocket.close();
    } catch (_error) {
      // The replacement connection still proceeds if a connecting socket cannot close cleanly.
    }
  }
  connect();
}

async function connect() {
  const settings = await loadSettings();
  if (!settings.pairingToken) {
    bridgeStatus = "not_configured";
    lastConnectionError = "No pairing token is saved in the extension.";
    nextRetryAt = 0;
    return;
  }
  if (socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(socket.readyState)) return;

  const generation = ++connectionGeneration;
  bridgeStatus = reconnectAttempt > 0 ? "reconnecting" : "connecting";
  const activeSocket = new WebSocket(websocketUrl(settings.bridgePort));
  socket = activeSocket;
  activeSocket.addEventListener("open", () => {
    if (generation !== connectionGeneration) return;
    activeSocket.send(JSON.stringify({
      type: "pair",
      token: settings.pairingToken,
      extension_version: chrome.runtime.getManifest().version
    }));
  });
  activeSocket.addEventListener("message", async (event) => {
    if (generation !== connectionGeneration) return;
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_error) {
      return;
    }
    if (message.type === "paired") {
      bridgeStatus = "paired";
      reconnectAttempt = 0;
      nextRetryAt = 0;
      lastConnectionError = null;
      clearTimeout(reconnectTimer);
      clearInterval(heartbeatTimer);
      heartbeatTimer = setInterval(() => void sendHeartbeat(), 20000);
      void sendHeartbeat();
      return;
    }
    if (message.protocol_version === 1 && message.request_id && message.command) {
      await handleCommand(message);
    }
  });
  activeSocket.addEventListener("close", (event) => {
    if (generation !== connectionGeneration) return;
    bridgeStatus = self.HKUConnectionLifecycle.closeState(event.code);
    lastConnectionError = event.reason || (
      event.code === 1006
        ? "The local HKU AGENTS service is unavailable."
        : `Bridge closed with code ${event.code}.`
    );
    socket = null;
    clearInterval(heartbeatTimer);
    scheduleReconnect();
  });
  activeSocket.addEventListener("error", () => {
    if (generation !== connectionGeneration) return;
    lastConnectionError = "Cannot reach the local HKU AGENTS browser bridge.";
  });
}

async function querySisTabs() {
  const tabs = await chrome.tabs.query({ url: SIS_URL_PATTERN });
  return tabs;
}

async function queryWeeklyTimetableTabs() {
  return chrome.tabs.query({ url: WEEKLY_TIMETABLE_URL_PATTERN });
}

async function queryMoodleTabs() {
  return chrome.tabs.query({ url: MOODLE_URL_PATTERN });
}

async function queryPortalTabs() {
  return chrome.tabs.query({ url: PORTAL_URL_PATTERNS });
}

function libraryResearchUrl(payload) {
  const query = String(payload?.query || "").trim();
  const fieldCodes = { any: "any", title: "title", author: "creator", subject: "sub" };
  const field = fieldCodes[payload?.field] || "any";
  if (query.length < 2 || query.length > 200) throw commandError("INVALID_INPUT", "Library query must contain 2 to 200 characters.");
  const url = new URL("https://julac-hku.primo.exlibrisgroup.com/discovery/search");
  url.searchParams.set("query", `${field},contains,${query}`);
  url.searchParams.set("tab", "HKU");
  url.searchParams.set("search_scope", payload?.scope === "everything" ? "MyInst_and_CI" : "MyInstitution");
  url.searchParams.set("vid", "852JULAC_HKU:HKU");
  url.searchParams.set("lang", "en");
  url.searchParams.set("offset", "0");
  return url.toString();
}

function libraryResearchDetailUrl(payload) {
  const recordId = String(payload?.record_id || "").trim();
  if (!/^[A-Za-z0-9_.:-]{3,120}$/.test(recordId)) {
    throw commandError("INVALID_INPUT", "Library record_id must be a stable Find@HKUL identifier.");
  }
  const url = new URL("https://julac-hku.primo.exlibrisgroup.com/discovery/fulldisplay");
  url.searchParams.set("docid", recordId);
  url.searchParams.set("vid", "852JULAC_HKU:HKU");
  url.searchParams.set("lang", "en");
  return url.toString();
}

const SPACE_ROUTES = Object.freeze({
  single_study_room: { location: "Main Library", booking_facility_type: "Single Study Room (3 sessions)" },
  av_group_viewing_room: { location: "Main Library", booking_facility_type: "AV Group Viewing Room" },
  communal_virtual_pc: { location: "Main Library", booking_facility_type: "Communal Virtual PC" },
  computer: { location: "Main Library", booking_facility_type: "Computer" },
  computer_in_lic: { location: "Main Library", booking_facility_type: "Computer in LIC" },
  engraving_cutting_computer: { location: "Main Library", booking_facility_type: "computer-controlled machines for engraving/cutting" },
  concept_and_creation_room: { location: "Main Library", booking_facility_type: "Concept and Creation Room" },
  discussion_room: { location: "Main Library", booking_facility_type: "Discussion Room" },
  microform_scanner: { location: "Main Library", booking_facility_type: "Special Collections - Microform Scanner" },
  overhead_scanner: { location: "Main Library", booking_facility_type: "Special Collections - Overhead Scanner" },
  research_desk: { location: "Main Library", booking_facility_type: "Special Collections - Research Desk" },
  studio_editing_room: { location: "Main Library", booking_facility_type: "Studio and Editing Room" },
  study_table: { location: "Main Library", booking_facility_type: "Study Table" },
  study_table_deep_quiet: { location: "Main Library", booking_facility_type: "Study Table (Deep Quiet)" },
  study_room: { location: "Chi Wah Learning Commons", booking_facility_type: "Study Room" }
});
const SPACE_AVAILABILITY_URL = "https://booking.lib.hku.hk/Secure/FacilityStatusDate.aspx";

async function waitForLibraryRead(tabId, command, payload, deadline, expectedPage = null, priorMatrixSignature = null) {
  let lastError = null;
  let previousReadySignature = null;
  while (Date.now() < deadline) {
    try {
      const snapshot = await sendTabCommand(tabId, command, payload);
      const diagnostics = snapshot?.diagnostics || {};
      const ready = command === "library.research.read_results"
        ? diagnostics.results_marker_found === true &&
          (diagnostics.result_candidate_count > 0 || diagnostics.empty_results_marker_found === true)
        : command === "library.research.read_item"
          ? diagnostics.detail_marker_found === true && diagnostics.metadata_field_count > 0
          : command === "library.research.read_access_options"
            ? diagnostics.detail_marker_found === true && diagnostics.parsed_access_option_count > 0
          : command === "library.hours.read"
            ? diagnostics.hours_marker_found === true &&
              (diagnostics.parsed_location_count > 0 || diagnostics.empty_state_found === true)
          : diagnostics.availability_marker_found === true &&
            diagnostics.selected_filters_found === true &&
            diagnostics.table_matrix_found === true &&
            (expectedPage === null || snapshot.page_number === expectedPage) &&
            (priorMatrixSignature === null || diagnostics.matrix_signature !== priorMatrixSignature);
      if (ready) {
        const signature = command === "library.research.read_results"
          ? `${diagnostics.result_candidate_count}|${diagnostics.parsed_result_count}|${diagnostics.incomplete_result_candidate_count}`
          : command === "library.research.read_item" || command === "library.research.read_access_options"
            ? `${snapshot.record_id || ""}|${snapshot.title || ""}|${diagnostics.metadata_field_count}|${diagnostics.parsed_access_option_count}`
            : command === "library.hours.read"
              ? `${snapshot.hours_available}|${diagnostics.row_count}|${diagnostics.parsed_location_count}|${diagnostics.empty_state_found}`
              : `${snapshot.location || ""}|${snapshot.booking_facility_type || ""}|${snapshot.date || ""}|${snapshot.page_number || 1}|${diagnostics.matrix_signature}|${diagnostics.slot_candidate_count}|${diagnostics.parsed_available_slot_count}|${diagnostics.unclassified_status_cell_count}|${diagnostics.neutral_nonselectable_cell_count}`;
        if (signature === previousReadySignature) return snapshot;
        previousReadySignature = signature;
      } else {
        previousReadySignature = null;
      }
    } catch (error) {
      if (error.code === "LIBRARY_LOGIN_REQUIRED") throw error;
      lastError = error;
    }
    await delay(400);
  }
  const code = command === "library.research.read_results"
    ? "LIBRARY_SEARCH_NOT_READY"
    : command === "library.research.read_item" || command === "library.research.read_access_options"
      ? "LIBRARY_ITEM_NOT_READY"
      : command === "library.hours.read"
        ? "LIBRARY_HOURS_NOT_READY"
        : "LIBRARY_SPACE_PAGE_NOT_READY";
  throw commandError(code, lastError?.message || "The HKUL page did not become ready before the deadline.");
}

async function searchLibraryResearch(payload) {
  const url = libraryResearchUrl(payload);
  const tab = await chrome.tabs.create({ url, active: false });
  const snapshot = await waitForLibraryRead(tab.id, "library.research.read_results", { limit: payload?.limit || 10 }, Date.now() + NAVIGATION_DEADLINE_MS);
  return {
    read_only: true,
    navigation_only: true,
    library_write_requests_sent: 0,
    navigation_interactions_performed: true,
    target_origin: "https://julac-hku.primo.exlibrisgroup.com",
    target_page_kind: "catalog_results",
    steps: ["library_fixed_route_to_research_results"],
    snapshot
  };
}

async function readLibraryResearchDetail(payload, mode) {
  const url = libraryResearchDetailUrl(payload);
  const tab = await chrome.tabs.create({ url, active: false });
  const readCommand = mode === "access_options" ? "library.research.read_access_options" : "library.research.read_item";
  const snapshot = await waitForLibraryRead(tab.id, readCommand, {}, Date.now() + NAVIGATION_DEADLINE_MS);
  if (snapshot.record_id !== String(payload.record_id)) {
    throw commandError("LIBRARY_RECORD_MISMATCH", "Find@HKUL opened a different record than requested.");
  }
  return {
    read_only: true,
    navigation_only: true,
    library_write_requests_sent: 0,
    navigation_interactions_performed: true,
    licensed_full_text_opened: 0,
    target_origin: "https://julac-hku.primo.exlibrisgroup.com",
    target_page_kind: "catalog_item",
    steps: ["library_fixed_route_to_research_item"],
    snapshot
  };
}

async function searchLibrarySpaceAvailability(payload, options = {}) {
  const facilityType = String(payload?.facility_type || "");
  const target = SPACE_ROUTES[facilityType];
  const date = String(payload?.date || "");
  if (!target || !/^20\d{2}-[01]\d-[0-3]\d$/.test(date)) {
    throw commandError("INVALID_INPUT", "Supported facility_type and exact YYYY-MM-DD date are required.");
  }
  const hongKongDateParts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit", day: "2-digit"
  }).formatToParts(new Date());
  const part = (type) => hongKongDateParts.find((item) => item.type === type)?.value || "";
  const hongKongToday = `${part("year")}-${part("month")}-${part("day")}`;
  const tomorrowDate = new Date(`${hongKongToday}T00:00:00Z`);
  tomorrowDate.setUTCDate(tomorrowDate.getUTCDate() + 1);
  const hongKongTomorrow = tomorrowDate.toISOString().slice(0, 10);
  if (date !== hongKongToday && date !== hongKongTomorrow) {
    throw commandError(
      "LIBRARY_SPACE_DATE_OUT_OF_WINDOW",
      `Choose ${hongKongToday} or ${hongKongTomorrow} (Hong Kong time) for the supported HKUL facilities.`
    );
  }
  const tab = await chrome.tabs.create({ url: SPACE_AVAILABILITY_URL, active: true });
  const deadline = Date.now() + NAVIGATION_DEADLINE_MS;
  const filterPayload = { ...target, date };
  let searchSubmitted = false;
  let configured = false;
  let lastConfigurationError = null;
  while (Date.now() < deadline) {
    try {
      const state = await sendTabCommand(
        tab.id,
        "library.spaces.configure_availability",
        { ...filterPayload, submit_search: !searchSubmitted }
      );
      if (state.availability_search_submitted) searchSubmitted = true;
      if (!state.navigation_started) {
        configured = true;
        break;
      }
    } catch (error) {
      lastConfigurationError = error;
      if (["INVALID_INPUT", "WRONG_LIBRARY_SPACE_PAGE", "LIBRARY_SPACE_FILTER_AMBIGUOUS", "LIBRARY_SPACE_SEARCH_AMBIGUOUS"].includes(error.code)) throw error;
    }
    await delay(500);
  }
  if (!configured) {
    throw commandError(
      lastConfigurationError?.code || "LIBRARY_SPACE_FILTERS_NOT_READY",
      lastConfigurationError?.message || "The exact HKUL booking filters did not become ready before the deadline."
    );
  }
  const firstPage = await waitForLibraryRead(tab.id, "library.spaces.read_availability", {}, deadline, 1);
  if (firstPage.location !== target.location || firstPage.booking_facility_type !== target.booking_facility_type || firstPage.date !== date) {
    throw commandError("LIBRARY_SPACE_FILTER_MISMATCH", "The live booking filters do not match the exact requested target.");
  }
  if (firstPage.page_count > 10) {
    throw commandError("LIBRARY_SPACE_RESULTS_PAGINATED", "The HKUL result has more than ten pages; controlled reading stopped.");
  }
  const pages = [firstPage];
  for (let page = 2; page <= firstPage.page_count; page += 1) {
    await sendTabCommand(tab.id, "library.spaces.select_result_page", { page_number: page });
    const current = await waitForLibraryRead(
      tab.id, "library.spaces.read_availability", {}, deadline, page,
      pages[pages.length - 1].diagnostics.matrix_signature
    );
    if (current.location !== target.location || current.booking_facility_type !== target.booking_facility_type ||
        current.date !== date || current.page_count !== firstPage.page_count) {
      throw commandError("LIBRARY_SPACE_RESULT_PAGE_MISMATCH", "A HKUL result page changed its filters or page count during reading.");
    }
    pages.push(current);
  }
  const slots = pages.flatMap((page) => page.available_slots.map((slot) => ({
    ...slot,
    page_number: page.page_number
  })));
  if (slots.length > 1000) {
    throw commandError("LIBRARY_SPACE_RESULTS_TOO_LARGE", "The HKUL result exceeded the bounded slot limit.");
  }
  const slotKeys = slots.map((slot) => `${slot.floor || ""}|${slot.room || ""}|${slot.start_time}|${slot.end_time}`);
  if (new Set(slotKeys).size !== slots.length) {
    throw commandError("LIBRARY_SPACE_RESULT_PAGE_DUPLICATE", "A HKUL result page repeated a previously read availability slot.");
  }
  const countFields = ["facility_row_count", "status_cell_count", "unclassified_status_cell_count",
    "neutral_nonselectable_cell_count", "slot_candidate_count", "incomplete_available_slot_candidate_count"];
  const diagnostics = { ...firstPage.diagnostics };
  for (const field of countFields) diagnostics[field] = pages.reduce((total, page) => total + Number(page.diagnostics[field] || 0), 0);
  diagnostics.unclassified_cell_shapes = pages.flatMap((page) =>
    (page.diagnostics.unclassified_cell_shapes || []).map((shape) => ({
      ...shape,
      page_number: page.page_number
    }))
  ).slice(0, 8);
  diagnostics.matrix_signature = pages[pages.length - 1].diagnostics.matrix_signature;
  diagnostics.parsed_available_slot_count = slots.length;
  diagnostics.verified_empty_result_found = pages.some((page) => page.diagnostics.verified_empty_result_found);
  diagnostics.result_set_complete = true;
  const snapshot = {
    ...pages[pages.length - 1],
    pages_read_count: pages.length,
    result_set_complete: true,
    available_slot_count: slots.length,
    available_slots: slots,
    diagnostics
  };
  const result = {
    read_only: true,
    navigation_only: true,
    library_write_requests_sent: 0,
    booking_writes_performed: 0,
    navigation_interactions_performed: true,
    target_origin: "https://booking.lib.hku.hk",
    target_page_kind: "space_availability",
    facility_type: facilityType,
    location: target.location,
    booking_facility_type: target.booking_facility_type,
    date,
    availability_search_submitted: searchSubmitted,
    page_navigation_interactions_performed: pages.length > 1,
    result_pages_read: pages.length,
    steps: ["library_fixed_route_to_space_availability", "library_set_exact_availability_filters"],
    snapshot
  };
  if (options.includeTabId === true) result.tab_id = tab.id;
  return result;
}

function exactSlotKey(slot) {
  return `${String(slot?.floor || "").trim()}|${String(slot?.room || "").trim()}|${slot?.start_time || ""}|${slot?.end_time || ""}`;
}

async function waitForBookingForm(tabId, target, deadline) {
  let prior = null;
  while (Date.now() < deadline) {
    try {
      const form = await sendTabCommand(tabId, "library.spaces.configure_booking_form", { target });
      if (form?.ready_to_submit === true && form.policy_notice_found === true) {
        const signature = JSON.stringify([form.selected_fields, form.session, form.submit_button_candidate_count]);
        if (signature === prior) return form;
        prior = signature;
      } else {
        prior = null;
      }
    } catch (error) {
      if (["WRONG_LIBRARY_SPACE_PAGE", "LIBRARY_BOOKING_FORM_MISMATCH", "INVALID_INPUT"].includes(error.code)) throw error;
      prior = null;
    }
    await delay(350);
  }
  throw commandError("LIBRARY_BOOKING_FORM_NOT_READY", "The exact HKUL booking form did not become ready before the deadline.");
}

async function ensureBookingAttemptUnused(executionId) {
  if (!/^[a-f0-9-]{36}$/i.test(String(executionId || ""))) {
    throw commandError("INVALID_INPUT", "A unique action execution ID is required.");
  }
  const { libraryBookingAttempts = [] } = await chrome.storage.local.get({ libraryBookingAttempts: [] });
  if (libraryBookingAttempts.some((attempt) => attempt?.execution_id === executionId)) {
    throw commandError("LIBRARY_BOOKING_ALREADY_ATTEMPTED", "This one-time booking execution ID was already armed; it will not be submitted again.");
  }
  const next = [
    ...libraryBookingAttempts.filter((attempt) => attempt && typeof attempt.execution_id === "string"),
    { execution_id: executionId, phase: "armed", armed_at: new Date().toISOString() }
  ];
  if (next.length > MAX_RECORDED_BOOKING_ATTEMPTS) {
    throw commandError("LIBRARY_BOOKING_ATTEMPT_STORE_FULL", "The bounded one-shot attempt ledger is full; no Submit was issued.");
  }
  await chrome.storage.local.set({ libraryBookingAttempts: next });
}

async function updateBookingAttempt(executionId, phase) {
  const { libraryBookingAttempts = [] } = await chrome.storage.local.get({ libraryBookingAttempts: [] });
  await chrome.storage.local.set({
    libraryBookingAttempts: libraryBookingAttempts.map((attempt) => attempt?.execution_id === executionId
      ? { ...attempt, phase, updated_at: new Date().toISOString() }
      : attempt)
  });
}

async function bookLibrarySpaceExactlyOnce(payload) {
  const facilityType = String(payload?.facility_type || "");
  const targetRoute = SPACE_ROUTES[facilityType];
  const target = payload?.target || {};
  if (payload?.operation === "submit") return submitPreparedLibraryBooking(payload);
  if (facilityType !== "single_study_room") {
    throw commandError(
      "LIBRARY_BOOKING_FACILITY_NOT_ENABLED",
      "F2 live submission is currently limited to Main Library single study rooms."
    );
  }
  if (payload?.operation !== "prepare" || !targetRoute ||
      target.facility_type !== facilityType || !target.date || !target.room || !target.floor ||
      !target.start_time || !target.end_time) {
    throw commandError("INVALID_INPUT", "A complete exact booking target is required for preparation.");
  }
  const availability = await searchLibrarySpaceAvailability(
    { facility_type: facilityType, date: target.date },
    { includeTabId: true }
  );
  const snapshot = availability.snapshot;
  const diagnostics = snapshot.diagnostics || {};
  if (snapshot.result_set_complete !== true || diagnostics.unclassified_status_cell_count > 0 ||
      diagnostics.incomplete_available_slot_candidate_count > 0 || diagnostics.parser_version !== "0.3.5") {
    throw commandError("LIBRARY_BOOKING_AVAILABILITY_INCOMPLETE", "The refreshed availability matrix was incomplete; no slot was selected.");
  }
  if (snapshot.location !== targetRoute.location || snapshot.booking_facility_type !== targetRoute.booking_facility_type || snapshot.date !== target.date) {
    throw commandError("LIBRARY_BOOKING_FILTER_MISMATCH", "The refreshed availability filters did not match the confirmed target.");
  }
  const expectedSlot = {
    floor: target.floor,
    room: target.room,
    start_time: target.start_time,
    end_time: target.end_time
  };
  const matches = snapshot.available_slots.filter((slot) => exactSlotKey(slot) === exactSlotKey(expectedSlot));
  if (matches.length !== 1) {
    throw commandError(matches.length ? "LIBRARY_BOOKING_SLOT_AMBIGUOUS" : "LIBRARY_BOOKING_SLOT_STALE", "The exact slot was not uniquely available after the final refresh.");
  }
  const slot = matches[0];
  let tab;
  try { tab = await chrome.tabs.get(availability.tab_id); } catch (_error) { tab = null; }
  if (!tab?.id || !String(tab.url || "").startsWith("https://booking.lib.hku.hk/")) {
    throw commandError("LIBRARY_BOOKING_TAB_NOT_FOUND", "The refreshed HKUL availability tab is no longer available.");
  }
  const current = await sendTabCommand(tab.id, "library.spaces.read_availability");
  if (current.page_number !== slot.page_number) {
    await sendTabCommand(tab.id, "library.spaces.select_result_page", { page_number: slot.page_number });
    const page = await waitForLibraryRead(tab.id, "library.spaces.read_availability", {}, Date.now() + NAVIGATION_DEADLINE_MS, slot.page_number, current.diagnostics?.matrix_signature || null);
    if (page.location !== targetRoute.location || page.booking_facility_type !== targetRoute.booking_facility_type || page.date !== target.date) {
      throw commandError("LIBRARY_BOOKING_FILTER_MISMATCH", "HKUL changed the exact availability filters before selection.");
    }
  }
  const selection = await sendTabCommand(tab.id, "library.spaces.select_exact_slot", { target });
  if (selection?.slot_selection_performed !== true || selection?.candidate_count !== 1) {
    throw commandError("LIBRARY_BOOKING_SLOT_SELECT_FAILED", "The exact available Select control was not confirmed.");
  }
  const form = await waitForBookingForm(tab.id, target, Date.now() + NAVIGATION_DEADLINE_MS);
  if (!form.ready_to_submit || !form.policy_notice_found) {
    throw commandError("LIBRARY_BOOKING_FORM_MISMATCH", "The form fields, selected session, or policy notice did not match; Submit was not clicked.");
  }

  return {
    read_only: true,
    navigation_interactions_performed: true,
    domain_writes_performed: 0,
    library_writes_performed: 0,
    booking_writes_performed: 0,
    slot_selection_performed: true,
    booking_form_opened: true,
    ready_to_submit: true,
    exact_target_verified: true,
    policy_notice_found: true,
    prepared_tab_id: tab.id,
    form_snapshot: form,
    diagnostics: {
      parser_version: "0.1.0",
      availability_matrix_complete: true,
      exact_slot_candidate_count: matches.length,
      submit_button_candidate_count: form.submit_button_candidate_count
    }
  };
}

async function submitPreparedLibraryBooking(payload) {
  const target = payload?.target || {};
  const executionId = String(payload?.execution_id || "");
  const preparedTabId = Number(payload?.prepared_tab_id);
  if (target.facility_type !== "single_study_room") {
    throw commandError(
      "LIBRARY_BOOKING_FACILITY_NOT_ENABLED",
      "F2 live submission is currently limited to Main Library single study rooms."
    );
  }
  if (payload?.policy_acceptance_acknowledged !== true || !target.facility_type ||
      !target.location || !target.date || !target.floor || !target.room ||
      !target.start_time || !target.end_time || !Number.isInteger(preparedTabId)) {
    throw commandError("INVALID_INPUT", "The confirmed exact target and explicit HKUL policy acknowledgment are required.");
  }
  let tab;
  try { tab = await chrome.tabs.get(preparedTabId); } catch (_error) { tab = null; }
  if (!tab?.id || !String(tab.url || "").startsWith("https://booking.lib.hku.hk/")) {
    throw commandError("LIBRARY_BOOKING_TAB_NOT_FOUND", "The prepared HKUL booking form is no longer available.");
  }
  const freshForm = await sendTabCommand(tab.id, "library.spaces.inspect_booking_form", { target });
  if (!freshForm?.ready_to_submit || !freshForm?.policy_notice_found) {
    throw commandError("LIBRARY_BOOKING_FORM_MISMATCH", "The live booking form no longer matches the confirmed action; Submit was not clicked.");
  }
  // Persist the one-shot key before dispatch. A worker restart or ambiguous
  // response can never cause the same action to click Submit twice.
  await ensureBookingAttemptUnused(executionId);
  let submit;
  try {
    submit = await sendTabCommand(tab.id, "library.spaces.submit_booking_once", { target });
    if (submit?.submit_click_dispatched !== true || submit?.submit_button_candidate_count !== 1) {
      throw commandError("LIBRARY_BOOKING_SUBMIT_NOT_CONFIRMED", "The browser did not confirm exactly one Submit click.");
    }
  } catch (error) {
    if (["LIBRARY_BOOKING_FORM_MISMATCH", "LIBRARY_BOOKING_SUBMIT_AMBIGUOUS", "LIBRARY_BOOKING_FORM_NOT_READY"].includes(error.code)) {
      await updateBookingAttempt(executionId, "not_submitted");
      throw error;
    }
    await updateBookingAttempt(executionId, "outcome_unknown");
    throw commandError("LIBRARY_BOOKING_OUTCOME_UNKNOWN", "The Submit action may have reached HKUL; inspect My Booking Record manually and do not retry this booking.");
  }
  await updateBookingAttempt(executionId, "submit_dispatched");
  try {
    await sendTabCommand(tab.id, "library.spaces.open_booking_record");
    let record = null;
    let priorSignature = null;
    const recordDeadline = Date.now() + NAVIGATION_DEADLINE_MS;
    while (Date.now() < recordDeadline) {
      try {
        record = await sendTabCommand(tab.id, "library.spaces.read_booking_record", { target });
        if (record?.record_page_marker_found) {
          const signature = `${record.exact_target_match_count}|${record.verified_exactly_once}`;
          if (signature === priorSignature) break;
          priorSignature = signature;
        }
      } catch (_error) {
        priorSignature = null;
      }
      await delay(350);
    }
    if (!record?.record_page_marker_found || record.exact_target_match_count !== 1 || record.verified_exactly_once !== true) {
      await updateBookingAttempt(executionId, "record_not_verified");
      throw commandError("LIBRARY_BOOKING_OUTCOME_UNKNOWN", "Submit was dispatched once, but the exact reservation could not be verified exactly once in My Booking Record. Do not retry; inspect the record manually.");
    }
    await updateBookingAttempt(executionId, "record_verified");
    return {
      read_only: false,
      systems_contacted: ["hkul_booking"],
      navigation_interactions_performed: true,
      data_reads_performed: 2,
      domain_writes_performed: 1,
      library_writes_performed: 1,
      booking_writes_performed: 1,
      slot_selection_performed: true,
      booking_form_opened: true,
      submit_clicks_dispatched: 1,
      outcome: "confirmed",
      exact_target_verified_in_booking_record: true,
      record_match_count: record.exact_target_match_count,
      policy_acceptance_acknowledged: true,
      diagnostics: {
        parser_version: "0.1.0",
        availability_matrix_refreshed_before_confirmation: true,
        exact_target_rechecked_before_submit: true,
        booking_form_ready: true,
        submit_button_candidate_count: freshForm.submit_button_candidate_count,
        record_diagnostics: record.diagnostics
      }
    };
  } catch (error) {
    await updateBookingAttempt(executionId, "outcome_unknown");
    if (error.code === "LIBRARY_BOOKING_OUTCOME_UNKNOWN") throw error;
    throw commandError("LIBRARY_BOOKING_OUTCOME_UNKNOWN", "Submit was dispatched once, but its outcome could not be verified. Inspect My Booking Record manually and do not retry.");
  }
}

async function readLibraryHoursAndLocations() {
  const tab = await chrome.tabs.create({ url: "https://lib.hku.hk/general/hours/", active: true });
  const snapshot = await waitForLibraryRead(tab.id, "library.hours.read", {}, Date.now() + NAVIGATION_DEADLINE_MS);
  return {
    read_only: true,
    navigation_only: true,
    library_write_requests_sent: 0,
    navigation_interactions_performed: true,
    target_origin: "https://lib.hku.hk",
    target_page_kind: "library_hours",
    steps: ["library_fixed_route_to_hours"],
    snapshot
  };
}

async function findAuthenticatedPortalTab() {
  const tabs = (await queryPortalTabs()).filter((tab) => !isKnownPortalErrorPage(tab.url));
  tabs.sort((left, right) =>
    Number(right.active) - Number(left.active) ||
    Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0)
  );
  for (const tab of tabs) {
    try {
      const snapshot = await sendTabCommand(tab.id, "hku.inspect_portal");
      if (snapshot.logged_in === true && snapshot.page_kind === "portal_home") return tab;
    } catch (_error) {
      // Continue across stale, login, or partially loaded Portal tabs.
    }
  }
  return null;
}

async function readPortalNotices() {
  const tab = await findAuthenticatedPortalTab();
  if (!tab) {
    throw commandError(
      "PORTAL_LOGIN_REQUIRED",
      "Open HKU Portal, complete login/MFA, and keep the home page available in Chrome."
    );
  }
  const snapshot = await sendTabCommand(tab.id, "portal.list_notices");
  boundTabId = tab.id;
  lastSnapshot = snapshot;
  void sendHeartbeat();
  return snapshot;
}

async function findSisTab() {
  const allTabs = await querySisTabs();
  const tabs = allTabs.filter((tab) => !isKnownSisSsoErrorPage(tab.url));
  if (!tabs.length && allTabs.some((tab) => isKnownSisSsoErrorPage(tab.url))) {
    throw commandError(
      "SIS_SSO_FAILED",
      "Only the PeopleSoft SSO error page is open; an authenticated SIS page is required."
    );
  }
  if (!tabs.length) throw commandError("SIS_TAB_NOT_FOUND", "Open HKU SIS in Chrome first.");
  tabs.sort((left, right) =>
    Number(right.active) - Number(left.active) || Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0)
  );
  return tabs[0];
}

function allowedOrigin(url) {
  try {
    const origin = new URL(url).origin;
    return PORTAL_ORIGINS.has(origin) || origin === SIS_ORIGIN ||
      origin === WEEKLY_TIMETABLE_ORIGIN || origin === MOODLE_ORIGIN
      ? origin
      : null;
  } catch (_error) {
    return null;
  }
}

function isKnownPortalErrorPage(url) {
  try {
    const parsed = new URL(url);
    return parsed.origin === "https://hkuportal.hku.hk" &&
      parsed.pathname.toLowerCase() === "/cas/login_error.html";
  } catch (_error) {
    return false;
  }
}

function isKnownSisSsoErrorPage(url) {
  const target = self.HKUBrowserTargets.classifyUrl(url);
  return target?.system === "sis" && target.page_kind === "sso_error";
}

function hkuTabPriority(tab) {
  const origin = allowedOrigin(tab?.url);
  if (origin === "https://studentportal.hku.hk") return 4;
  if (origin === WEEKLY_TIMETABLE_ORIGIN) return 3;
  if (origin === MOODLE_ORIGIN) return 3;
  if (origin === SIS_ORIGIN) return 2;
  if (origin === "https://hkuportal.hku.hk") return 1;
  return 0;
}

async function findHkuTab() {
  const active = await chrome.tabs.query({ active: true, currentWindow: true });
  if (
    active[0]?.url &&
    allowedOrigin(active[0].url) &&
    !isKnownPortalErrorPage(active[0].url) &&
    !isKnownSisSsoErrorPage(active[0].url)
  ) return active[0];
  const tabs = (await chrome.tabs.query({
    url: [...PORTAL_URL_PATTERNS, SIS_URL_PATTERN, WEEKLY_TIMETABLE_URL_PATTERN, MOODLE_URL_PATTERN]
  }))
    .filter((tab) => !isKnownPortalErrorPage(tab.url) && !isKnownSisSsoErrorPage(tab.url));
  if (!tabs.length) {
    throw commandError(
      "HKU_TAB_NOT_FOUND",
      "Open and sign in to HKU Portal, then keep that tab active."
    );
  }
  tabs.sort((left, right) =>
    hkuTabPriority(right) - hkuTabPriority(left) ||
    Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0)
  );
  return tabs[0];
}

async function sendTabCommand(tabId, command, payload = {}) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, { command, payload });
    if (!response || !response.ok) {
      throw commandError(
        response?.error?.code || "PAGE_SCRIPT_UNAVAILABLE",
        response?.error?.message || "Reload the verified HKU tab after updating the extension."
      );
    }
    return response.data;
  } catch (error) {
    if (error.code) throw error;
    throw commandError(
      "PAGE_SCRIPT_UNAVAILABLE",
      "Reload the verified HKU Portal or SIS tab after updating the extension."
    );
  }
}

async function inspectBoundHkuTab() {
  let tab;
  if (boundTabId !== null) {
    try {
      tab = await chrome.tabs.get(boundTabId);
    } catch (_error) {
      boundTabId = null;
    }
  }
  if (
    !tab?.url ||
    !allowedOrigin(tab.url) ||
    isKnownPortalErrorPage(tab.url) ||
    isKnownSisSsoErrorPage(tab.url)
  ) {
    tab = await findHkuTab();
  }
  const origin = allowedOrigin(tab.url);
  const command = PORTAL_ORIGINS.has(origin)
    ? "hku.inspect_portal"
    : origin === WEEKLY_TIMETABLE_ORIGIN
      ? "timetable.inspect_weekly"
      : origin === MOODLE_ORIGIN
        ? "moodle.inspect_dashboard"
      : "sis.inspect_page";
  const snapshot = await sendTabCommand(tab.id, command);
  boundTabId = tab.id;
  lastSnapshot = snapshot;
  void sendHeartbeat();
  return lastSnapshot;
}

async function inspectBoundSisTab(command, payload = {}) {
  let tab;
  if (boundTabId !== null) {
    try {
      tab = await chrome.tabs.get(boundTabId);
    } catch (_error) {
      boundTabId = null;
    }
  }
  if (
    !tab?.url ||
    allowedOrigin(tab.url) !== SIS_ORIGIN ||
    isKnownSisSsoErrorPage(tab.url)
  ) {
    tab = await findSisTab();
    boundTabId = tab.id;
  }
  const data = await sendTabCommand(boundTabId, command, payload);
  if (!["sis.open_enrollment_add_classes", "sis.select_term"].includes(command)) {
    lastSnapshot = data;
  }
  void sendHeartbeat();
  return data;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForSisSnapshot(deadline, preferredTabId = null, existingSisTabIds = new Set()) {
  let lastError = null;
  let ssoFailureSeenAt = null;
  while (Date.now() < deadline) {
    try {
      const sisTabs = await querySisTabs();
      if (sisTabs.some((tab) => isKnownSisSsoErrorPage(tab.url))) {
        ssoFailureSeenAt ??= Date.now();
      }
      const candidates = sisTabs.filter((tab) => !isKnownSisSsoErrorPage(tab.url));
      candidates.sort((left, right) =>
        Number(!existingSisTabIds.has(right.id)) - Number(!existingSisTabIds.has(left.id)) ||
        Number(right.id === preferredTabId) - Number(left.id === preferredTabId) ||
        Number(right.openerTabId === preferredTabId) - Number(left.openerTabId === preferredTabId) ||
        Number(right.active) - Number(left.active) ||
        Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0)
      );
      if (!candidates.length) {
        if (ssoFailureSeenAt && Date.now() - ssoFailureSeenAt >= 2000) {
          throw commandError(
            "SIS_SSO_FAILED",
            "HKU Portal opened the PeopleSoft SSO error page instead of an authenticated SIS session."
          );
        }
        await delay(300);
        continue;
      }
      for (const tab of candidates) {
        try {
          const snapshot = await sendTabCommand(tab.id, "sis.inspect_page");
          if (snapshot.logged_in === true) {
            boundTabId = tab.id;
            lastSnapshot = snapshot;
            void sendHeartbeat();
            return snapshot;
          }
          if (snapshot.logged_in === false) {
            lastError = commandError("SIS_LOGIN_REQUIRED", "Complete SIS authentication in Chrome.");
          }
        } catch (error) {
          lastError = error;
        }
      }
    } catch (error) {
      if (error.code === "SIS_SSO_FAILED") throw error;
      lastError = error;
    }
    if (ssoFailureSeenAt && Date.now() - ssoFailureSeenAt >= 2000) {
      throw commandError(
        "SIS_SSO_FAILED",
        "HKU Portal opened the PeopleSoft SSO error page instead of an authenticated SIS session."
      );
    }
    await delay(300);
  }
  throw commandError(
    "NAVIGATION_TIMEOUT",
    lastError?.message || "SIS did not open before the navigation deadline."
  );
}

async function findAuthenticatedSisSnapshot() {
  const tabs = (await querySisTabs()).filter((tab) => !isKnownSisSsoErrorPage(tab.url));
  tabs.sort((left, right) =>
    Number(right.active) - Number(left.active) ||
    Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0)
  );
  for (const tab of tabs) {
    try {
      const snapshot = await sendTabCommand(tab.id, "sis.inspect_page");
      if (snapshot.logged_in === true) {
        boundTabId = tab.id;
        lastSnapshot = snapshot;
        void sendHeartbeat();
        return snapshot;
      }
    } catch (_error) {
      // Continue across stale tabs and tabs that have not loaded the content script.
    }
  }
  return null;
}

async function findAuthenticatedWeeklyTimetableSnapshot() {
  const tabs = await queryWeeklyTimetableTabs();
  tabs.sort((left, right) =>
    Number(right.active) - Number(left.active) ||
    Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0)
  );
  for (const tab of tabs) {
    try {
      const snapshot = await sendTabCommand(tab.id, "timetable.inspect_weekly");
      if (snapshot.logged_in === true && snapshot.page_kind === "weekly_timetable") {
        boundTabId = tab.id;
        lastSnapshot = snapshot;
        void sendHeartbeat();
        return snapshot;
      }
    } catch (_error) {
      // Continue across stale or partially loaded timetable tabs.
    }
  }
  return null;
}

async function findAuthenticatedMoodleSnapshot(allowAuthenticatedPage = false) {
  const tabs = await queryMoodleTabs();
  tabs.sort((left, right) =>
    Number(right.active) - Number(left.active) ||
    Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0)
  );
  for (const tab of tabs) {
    try {
      const snapshot = await sendTabCommand(tab.id, "moodle.inspect_dashboard");
      const acceptablePage = snapshot.page_kind === "dashboard" ||
        (allowAuthenticatedPage && ["home", "course"].includes(snapshot.page_kind));
      if (snapshot.logged_in === true && acceptablePage) {
        boundTabId = tab.id;
        lastSnapshot = snapshot;
        void sendHeartbeat();
        return snapshot;
      }
    } catch (_error) {
      // Continue across stale, login, or partially loaded Moodle tabs.
    }
  }
  return null;
}

async function waitForWeeklyTimetableSnapshot(deadline, preferredTabId = null) {
  let lastError = null;
  while (Date.now() < deadline) {
    const tabs = await queryWeeklyTimetableTabs();
    tabs.sort((left, right) =>
      Number(right.id === preferredTabId) - Number(left.id === preferredTabId) ||
      Number(right.active) - Number(left.active) ||
      Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0)
    );
    for (const tab of tabs) {
      try {
        const snapshot = await sendTabCommand(tab.id, "timetable.inspect_weekly");
        if (snapshot.logged_in === true && snapshot.page_kind === "weekly_timetable") {
          boundTabId = tab.id;
          lastSnapshot = snapshot;
          void sendHeartbeat();
          return snapshot;
        }
        if (snapshot.logged_in === false) {
          lastError = commandError(
            "TIMETABLE_LOGIN_REQUIRED",
            "Complete HKU authentication for My Weekly Schedule in Chrome."
          );
        }
      } catch (error) {
        lastError = error;
      }
    }
    await delay(300);
  }
  throw commandError(
    lastError?.code || "TIMETABLE_NAVIGATION_TIMEOUT",
    lastError?.message || "My Weekly Schedule did not become ready before the navigation deadline."
  );
}

async function waitForMoodleDashboardSnapshot(deadline, preferredTabId = null) {
  let lastError = null;
  const dashboardNavigationTabIds = new Set();
  const ssoNavigationTabIds = new Set();
  while (Date.now() < deadline) {
    const tabs = await queryMoodleTabs();
    tabs.sort((left, right) =>
      Number(right.openerTabId === preferredTabId) - Number(left.openerTabId === preferredTabId) ||
      Number(right.active) - Number(left.active) ||
      Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0)
    );
    for (const tab of tabs) {
      try {
        const snapshot = await sendTabCommand(tab.id, "moodle.inspect_dashboard");
        if (snapshot.logged_in === true && snapshot.page_kind === "dashboard") {
          boundTabId = tab.id;
          lastSnapshot = snapshot;
          void sendHeartbeat();
          return {
            snapshot,
            dashboardNavigationPerformed: dashboardNavigationTabIds.has(tab.id),
            ssoInteractionPerformed: ssoNavigationTabIds.size > 0
          };
        }
        if (snapshot.logged_in === false) {
          if (snapshot.page_kind === "login" && !ssoNavigationTabIds.has(tab.id)) {
            await sendTabCommand(tab.id, "moodle.start_portal_sso");
            ssoNavigationTabIds.add(tab.id);
            lastError = commandError(
              "MOODLE_SSO_IN_PROGRESS",
              "The verified HKU Portal User SSO flow has started."
            );
          } else {
            lastError = commandError(
              "SSO_MANUAL_ACTION_REQUIRED",
              "Complete any password, MFA, CAPTCHA, consent, or recovery prompt in Chrome."
            );
          }
          continue;
        }
        if (
          snapshot.logged_in === true &&
          ["home", "course"].includes(snapshot.page_kind) &&
          !dashboardNavigationTabIds.has(tab.id)
        ) {
          await sendTabCommand(tab.id, "moodle.open_dashboard");
          dashboardNavigationTabIds.add(tab.id);
          lastError = commandError(
            "MOODLE_DASHBOARD_NOT_READY",
            "Moodle is authenticated and is opening the fixed Dashboard route."
          );
        } else {
          lastError = commandError(
            "MOODLE_DASHBOARD_NOT_READY",
            `Moodle opened page kind '${snapshot.page_kind}', not the verified Dashboard.`
          );
        }
      } catch (error) {
        if (["MOODLE_SSO_ENTRY_NOT_FOUND", "MOODLE_SSO_ENTRY_AMBIGUOUS"].includes(error.code)) {
          lastError = commandError(
            "SSO_MANUAL_ACTION_REQUIRED",
            "Use the HKU Portal User login control in Moodle, then complete any required authentication prompt."
          );
        } else {
          lastError = error;
        }
      }
    }
    await delay(300);
  }
  if (ssoNavigationTabIds.size > 0 && lastError?.code === "MOODLE_SSO_IN_PROGRESS") {
    throw commandError(
      "SSO_MANUAL_ACTION_REQUIRED",
      "The HKU SSO flow did not return to Moodle; complete any visible authentication prompt in Chrome."
    );
  }
  throw commandError(
    lastError?.code || "MOODLE_NAVIGATION_TIMEOUT",
    lastError?.message || "Moodle Dashboard did not become ready before the navigation deadline."
  );
}

async function readSettledMoodleCourseList(deadline = Date.now() + 5000) {
  const dashboard = await findAuthenticatedMoodleSnapshot();
  if (!dashboard) {
    throw commandError("MOODLE_TAB_NOT_FOUND", "Open the authenticated Moodle Dashboard in Chrome first.");
  }
  let lastSnapshot = null;
  while (Date.now() < deadline) {
    lastSnapshot = await sendTabCommand(boundTabId, "moodle.list_courses");
    const diagnostics = lastSnapshot.diagnostics || {};
    if (
      Number(diagnostics.parsed_course_count || 0) > 0 &&
      Number(diagnostics.unparsed_course_candidate_count || 0) === 0
    ) {
      return lastSnapshot;
    }
    await delay(300);
  }
  return lastSnapshot;
}

async function readSettledMoodleAssignments(deadline = Date.now() + 5000) {
  const dashboard = await findAuthenticatedMoodleSnapshot();
  if (!dashboard) {
    throw commandError("MOODLE_TAB_NOT_FOUND", "Open the authenticated Moodle Dashboard in Chrome first.");
  }
  let snapshot = null;
  while (Date.now() < deadline) {
    snapshot = await sendTabCommand(boundTabId, "moodle.list_upcoming_assignments");
    const diagnostics = snapshot.diagnostics || {};
    if (
      Number(diagnostics.parsed_assignment_count || 0) > 0 &&
      Number(diagnostics.unparsed_assignment_candidate_count || 0) === 0
    ) {
      return snapshot;
    }
    await delay(300);
  }
  return snapshot;
}

async function waitForCartSnapshot(deadline, requestedTermLabel = null) {
  let lastError = null;
  let selectedTerm = false;
  while (Date.now() < deadline) {
    try {
      const snapshot = await inspectBoundSisTab("sis.inspect_page");
      if (snapshot.logged_in === false) {
        throw commandError("SIS_LOGIN_REQUIRED", "Complete SIS authentication in Chrome.");
      }
      if (snapshot.page_kind === "cart" && snapshot.logged_in === true) {
        return { snapshot, selectedTerm };
      }
      if (snapshot.page_kind === "term_selection" && !selectedTerm) {
        if (!requestedTermLabel) {
          const available = Array.isArray(snapshot.available_terms)
            ? snapshot.available_terms.join(", ")
            : "";
          throw commandError(
            "TERM_SELECTION_REQUIRED",
            available
              ? `Select a target term before navigation. Available terms: ${available}.`
              : "Select a target term before navigation."
          );
        }
        await inspectBoundSisTab("sis.select_term", { term_label: requestedTermLabel });
        selectedTerm = true;
      }
    } catch (error) {
      if ([
        "SIS_LOGIN_REQUIRED",
        "TERM_SELECTION_REQUIRED",
        "TERM_NOT_AVAILABLE",
        "TERM_MISMATCH",
        "TERM_SELECTION_AMBIGUOUS",
        "INVALID_TERM_LABEL",
        "NAVIGATION_TARGET_NOT_FOUND",
        "NAVIGATION_TARGET_AMBIGUOUS"
      ].includes(error.code)) throw error;
      lastError = error;
    }
    await delay(300);
  }
  throw commandError(
    "NAVIGATION_TIMEOUT",
    lastError?.message || "Enrollment Add Classes did not become ready before the navigation deadline."
  );
}

async function openSisOutcome(deadline = Date.now() + NAVIGATION_DEADLINE_MS) {
  const snapshot = await inspectBoundHkuTab();
  if (snapshot.origin === SIS_ORIGIN) {
    return { snapshot, portalNavigationPerformed: false };
  }
  if (!PORTAL_ORIGINS.has(snapshot.origin) || snapshot.page_kind !== "portal_home") {
    throw commandError("PORTAL_LOGIN_REQUIRED", "Complete HKU Portal login and MFA first.");
  }
  const authenticatedSis = await findAuthenticatedSisSnapshot();
  if (authenticatedSis) {
    return { snapshot: authenticatedSis, portalNavigationPerformed: false };
  }
  const portalTabId = boundTabId;
  const existingSisTabIds = new Set((await querySisTabs()).map((tab) => tab.id));
  await sendTabCommand(portalTabId, "hku.open_sis");
  return {
    snapshot: await waitForSisSnapshot(deadline, portalTabId, existingSisTabIds),
    portalNavigationPerformed: true
  };
}

async function openSis(deadline = Date.now() + NAVIGATION_DEADLINE_MS) {
  return (await openSisOutcome(deadline)).snapshot;
}

async function openWeeklyTimetable() {
  const deadline = Date.now() + NAVIGATION_DEADLINE_MS;
  const source = await inspectBoundHkuTab();
  if (
    source.origin === WEEKLY_TIMETABLE_ORIGIN &&
    source.logged_in === true &&
    source.page_kind === "weekly_timetable"
  ) {
    return {
      read_only: true,
      navigation_only: true,
      timetable_write_requests_sent: 0,
      source_origin: source.origin,
      source_page_kind: source.page_kind,
      target_origin: WEEKLY_TIMETABLE_ORIGIN,
      target_page_kind: "weekly_timetable",
      steps: ["target_already_open"],
      snapshot: source
    };
  }
  if (!PORTAL_ORIGINS.has(source.origin) || source.page_kind !== "portal_home") {
    throw commandError(
      "PORTAL_LOGIN_REQUIRED",
      "Open and authenticate HKU Portal before synchronizing My Weekly Schedule."
    );
  }
  const existing = await findAuthenticatedWeeklyTimetableSnapshot();
  if (existing) {
    return {
      read_only: true,
      navigation_only: true,
      timetable_write_requests_sent: 0,
      source_origin: source.origin,
      source_page_kind: source.page_kind,
      target_origin: WEEKLY_TIMETABLE_ORIGIN,
      target_page_kind: "weekly_timetable",
      steps: ["weekly_timetable_tab_reused"],
      snapshot: existing
    };
  }
  const portalTabId = boundTabId;
  await sendTabCommand(portalTabId, "hku.open_weekly_timetable");
  const snapshot = await waitForWeeklyTimetableSnapshot(deadline, portalTabId);
  return {
    read_only: true,
    navigation_only: true,
    timetable_write_requests_sent: 0,
    source_origin: source.origin,
    source_page_kind: source.page_kind,
    target_origin: WEEKLY_TIMETABLE_ORIGIN,
    target_page_kind: "weekly_timetable",
    steps: ["portal_to_weekly_timetable"],
    snapshot
  };
}

async function openMoodleDashboard() {
  const deadline = Date.now() + NAVIGATION_DEADLINE_MS;
  let source = await inspectBoundHkuTab();
  let portalTabId = PORTAL_ORIGINS.has(source.origin) ? boundTabId : null;
  let portalSessionReused = source.logged_in === true && PORTAL_ORIGINS.has(source.origin);
  if (
    source.origin === MOODLE_ORIGIN &&
    source.logged_in === true &&
    source.page_kind === "dashboard"
  ) {
    return {
      read_only: true,
      navigation_only: true,
      moodle_write_requests_sent: 0,
      source_origin: source.origin,
      source_page_kind: source.page_kind,
      target_origin: MOODLE_ORIGIN,
      target_page_kind: "dashboard",
      portal_session_reused: false,
      moodle_session_reused: true,
      sso_interactions_performed: false,
      credentials_entered: false,
      mfa_interactions_performed: false,
      steps: ["target_already_open"],
      snapshot: source
    };
  }
  if (
    source.origin === MOODLE_ORIGIN &&
    source.logged_in === true &&
    ["home", "course"].includes(source.page_kind)
  ) {
    const moodleTabId = boundTabId;
    await sendTabCommand(moodleTabId, "moodle.open_dashboard");
    const outcome = await waitForMoodleDashboardSnapshot(deadline, moodleTabId);
    return {
      read_only: true,
      navigation_only: true,
      moodle_write_requests_sent: 0,
      source_origin: source.origin,
      source_page_kind: source.page_kind,
      target_origin: MOODLE_ORIGIN,
      target_page_kind: "dashboard",
      portal_session_reused: false,
      moodle_session_reused: true,
      sso_interactions_performed: outcome.ssoInteractionPerformed,
      credentials_entered: false,
      mfa_interactions_performed: false,
      steps: ["moodle_fixed_route_to_dashboard"],
      snapshot: outcome.snapshot
    };
  }
  if (!PORTAL_ORIGINS.has(source.origin) || source.page_kind !== "portal_home") {
    const portalTab = await findAuthenticatedPortalTab();
    if (!portalTab) {
      throw commandError(
        source.origin === MOODLE_ORIGIN ? "MOODLE_LOGIN_REQUIRED" : "PORTAL_LOGIN_REQUIRED",
        "Open HKU Portal and complete login/MFA before continuing to Moodle."
      );
    }
    source = await sendTabCommand(portalTab.id, "hku.inspect_portal");
    portalTabId = portalTab.id;
    portalSessionReused = true;
    boundTabId = portalTab.id;
    lastSnapshot = source;
  }
  const existing = await findAuthenticatedMoodleSnapshot(true);
  if (existing) {
    if (existing.page_kind !== "dashboard") {
      const moodleTabId = boundTabId;
      await sendTabCommand(moodleTabId, "moodle.open_dashboard");
      const outcome = await waitForMoodleDashboardSnapshot(deadline, moodleTabId);
      return {
        read_only: true,
        navigation_only: true,
        moodle_write_requests_sent: 0,
        source_origin: source.origin,
        source_page_kind: source.page_kind,
        target_origin: MOODLE_ORIGIN,
        target_page_kind: "dashboard",
        portal_session_reused: portalSessionReused,
        moodle_session_reused: true,
        sso_interactions_performed: outcome.ssoInteractionPerformed,
        credentials_entered: false,
        mfa_interactions_performed: false,
        steps: ["moodle_tab_reused", "moodle_fixed_route_to_dashboard"],
        snapshot: outcome.snapshot
      };
    }
    return {
      read_only: true,
      navigation_only: true,
      moodle_write_requests_sent: 0,
      source_origin: source.origin,
      source_page_kind: source.page_kind,
      target_origin: MOODLE_ORIGIN,
      target_page_kind: "dashboard",
      portal_session_reused: portalSessionReused,
      moodle_session_reused: true,
      sso_interactions_performed: false,
      credentials_entered: false,
      mfa_interactions_performed: false,
      steps: ["moodle_dashboard_tab_reused"],
      snapshot: existing
    };
  }
  const portalNavigation = await sendTabCommand(portalTabId, "hku.open_moodle");
  const outcome = await waitForMoodleDashboardSnapshot(deadline, portalTabId);
  const steps = ["portal_to_moodle"];
  const ssoInteractionsPerformed = Boolean(
    portalNavigation.portal_sso_entry_clicked || outcome.ssoInteractionPerformed
  );
  if (ssoInteractionsPerformed) steps.push("moodle_portal_sso_started");
  if (outcome.dashboardNavigationPerformed) steps.push("moodle_fixed_route_to_dashboard");
  return {
    read_only: true,
    navigation_only: true,
    moodle_write_requests_sent: 0,
    source_origin: source.origin,
    source_page_kind: source.page_kind,
    target_origin: MOODLE_ORIGIN,
    target_page_kind: "dashboard",
    portal_session_reused: portalSessionReused,
    moodle_session_reused: false,
    sso_interactions_performed: ssoInteractionsPerformed,
    credentials_entered: false,
    mfa_interactions_performed: false,
    steps,
    snapshot: outcome.snapshot
  };
}

async function openEnrollmentAddClasses(requestedTermLabel = null) {
  const deadline = Date.now() + NAVIGATION_DEADLINE_MS;
  const source = await inspectBoundHkuTab();
  if (
    source.page_kind === "cart" &&
    requestedTermLabel &&
    source.term_label !== requestedTermLabel
  ) {
    throw commandError(
      "TERM_MISMATCH",
      `The open SIS cart is '${source.term_label || "unknown"}', not '${requestedTermLabel}'.`
    );
  }
  const steps = [];
  let sisSessionReused = false;
  let sisSnapshot = source;
  if (PORTAL_ORIGINS.has(source.origin)) {
    const sisOutcome = await openSisOutcome(deadline);
    sisSnapshot = sisOutcome.snapshot;
    if (sisOutcome.portalNavigationPerformed) {
      steps.push("portal_to_sis");
    } else {
      sisSessionReused = true;
    }
  }
  if (sisSnapshot.origin !== SIS_ORIGIN || sisSnapshot.logged_in !== true) {
    throw commandError("SIS_LOGIN_REQUIRED", "An authenticated SIS page is required.");
  }
  if (sisSnapshot.page_kind !== "cart") {
    await inspectBoundSisTab("sis.open_enrollment_add_classes");
    const navigationOutcome = await waitForCartSnapshot(deadline, requestedTermLabel);
    sisSnapshot = navigationOutcome.snapshot;
    steps.push("sis_fixed_route_to_enrollment_add_classes");
    if (navigationOutcome.selectedTerm) steps.push("sis_select_term");
  }
  if (steps.length === 0) steps.push("target_already_open");
  return {
    read_only: true,
    navigation_only: true,
    sis_write_requests_sent: 0,
    source_origin: source.origin,
    source_page_kind: source.page_kind,
    target_origin: SIS_ORIGIN,
    target_page_kind: "cart",
    sis_session_reused: sisSessionReused,
    steps,
    snapshot: sisSnapshot
  };
}

function commandError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

async function executeCommand(command, payload = {}) {
  if (!ALLOWED_COMMANDS.has(command)) {
    throw commandError("COMMAND_NOT_ALLOWED", "This extension only accepts named, bounded commands; general-purpose browser execution is unavailable.");
  }
  if (command === "browser.health") {
    await refreshTargetRegistry();
    return { connected: bridgeStatus === "paired", read_only: true, targets: targetRegistry };
  }
  if (command === "hku.bind_tab") {
    const tab = await findHkuTab();
    const origin = allowedOrigin(tab.url);
    const inspectCommand = PORTAL_ORIGINS.has(origin)
      ? "hku.inspect_portal"
      : origin === WEEKLY_TIMETABLE_ORIGIN
        ? "timetable.inspect_weekly"
        : origin === MOODLE_ORIGIN
          ? "moodle.inspect_dashboard"
        : "sis.inspect_page";
    const snapshot = await sendTabCommand(tab.id, inspectCommand);
    boundTabId = tab.id;
    lastSnapshot = snapshot;
    void sendHeartbeat();
    return snapshot;
  }
  if (command === "hku.inspect_portal") return inspectBoundHkuTab();
  if (command === "hku.open_sis") return openSis();
  if (command === "hku.open_weekly_timetable") return openWeeklyTimetable();
  if (command === "hku.open_moodle") return openMoodleDashboard();
  if (command === "portal.list_notices") return readPortalNotices();
  if (command === "hku.open_enrollment_add_classes") {
    return openEnrollmentAddClasses(payload.term_label || null);
  }
  if (command === "sis.bind_tab") {
    const tab = await findSisTab();
    boundTabId = tab.id;
    return inspectBoundSisTab("sis.inspect_page");
  }
  if (command === "sis.open_enrollment_add_classes") {
    return openEnrollmentAddClasses(payload.term_label || null);
  }
  if (command === "sis.select_term") return inspectBoundSisTab(command, payload);
  if (command === "sis.preflight") return inspectBoundSisTab("sis.inspect_cart");
  if (command === "timetable.inspect_weekly") {
    const snapshot = await findAuthenticatedWeeklyTimetableSnapshot();
    if (!snapshot) {
      throw commandError("TIMETABLE_TAB_NOT_FOUND", "Open My Weekly Schedule in Chrome first.");
    }
    return snapshot;
  }
  if (command === "moodle.inspect_dashboard") {
    const snapshot = await findAuthenticatedMoodleSnapshot();
    if (!snapshot) {
      throw commandError("MOODLE_TAB_NOT_FOUND", "Open the authenticated Moodle Dashboard in Chrome first.");
    }
    return snapshot;
  }
  if (command === "moodle.list_courses") {
    return readSettledMoodleCourseList();
  }
  if (command === "moodle.list_upcoming_assignments") {
    return readSettledMoodleAssignments();
  }
  if (command === "library.research.search") return searchLibraryResearch(payload);
  if (command === "library.research.item") return readLibraryResearchDetail(payload, "item");
  if (command === "library.research.access_options") return readLibraryResearchDetail(payload, "access_options");
  if (command === "library.spaces.search_availability") return searchLibrarySpaceAvailability(payload);
  if (command === "library.spaces.book_exact_once") return bookLibrarySpaceExactlyOnce(payload);
  if (command === "library.hours_and_locations") return readLibraryHoursAndLocations();
  return inspectBoundSisTab(command);
}

async function handleCommand(message) {
  const response = { protocol_version: 1, request_id: message.request_id, ok: false, data: {} };
  try {
    response.data = await executeCommand(message.command, message.payload || {});
    response.ok = true;
  } catch (error) {
    response.error = {
      code: String(error.code || "BROWSER_COMMAND_FAILED"),
      message: String(error.message || error)
    };
  }
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(response));
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "configure") {
    chrome.storage.local.set({
      pairingToken: String(message.pairingToken || ""),
      bridgePort: Number(message.bridgePort || 7860)
    }).then(() => {
      restartConnection();
      sendResponse({ ok: true });
    });
    return true;
  }
  if (message?.type === "status") {
    refreshTargetRegistry().catch(() => targetRegistry).then(() => {
      const status = self.HKUConnectionLifecycle.visibleState(
        bridgeStatus,
        lastSnapshot ? { ...lastSnapshot, bound: boundTabId !== null } : null
      );
      sendResponse({
        status,
        transportStatus: bridgeStatus,
        bound: boundTabId !== null,
        pageKind: lastSnapshot?.page_kind || "unknown",
        targets: targetRegistry,
        lastError: lastConnectionError,
        reconnectAttempt,
        retryInSeconds: nextRetryAt > Date.now()
          ? Math.max(1, Math.ceil((nextRetryAt - Date.now()) / 1000))
          : 0
      });
    });
    return true;
  }
  if (message?.type === "reconnect") {
    restartConnection();
    sendResponse({ ok: true });
    return false;
  }
  if (message?.type === "bind") {
    executeCommand("hku.bind_tab")
      .then((data) => sendResponse({ ok: true, data }))
      .catch((error) => sendResponse({
        ok: false,
        error: { code: error.code || "BIND_FAILED", message: error.message }
      }));
    return true;
  }
  return false;
});

chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();
