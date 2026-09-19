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
  "library.spaces.search_availability"
]);
const NAVIGATION_DEADLINE_MS = 30000;

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
  single_study_room: "https://booking.lib.hku.hk/FView.aspx?ftype=31&lib=3",
  studio_editing_room: "https://booking.lib.hku.hk/FView.aspx?ftype=34&lib=3",
  study_table: "https://booking.lib.hku.hk/table"
});

async function waitForLibraryRead(tabId, command, payload, deadline) {
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
          : diagnostics.availability_marker_found === true;
      if (ready) {
        const signature = command === "library.research.read_results"
          ? `${diagnostics.result_candidate_count}|${diagnostics.parsed_result_count}|${diagnostics.incomplete_result_candidate_count}`
          : command === "library.research.read_item" || command === "library.research.read_access_options"
            ? `${snapshot.record_id || ""}|${snapshot.title || ""}|${diagnostics.metadata_field_count}|${diagnostics.parsed_access_option_count}`
            : `${snapshot.date || ""}|${diagnostics.slot_candidate_count}|${diagnostics.parsed_available_slot_count}`;
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

async function searchLibrarySpaceAvailability(payload) {
  const facilityType = String(payload?.facility_type || "");
  const url = SPACE_ROUTES[facilityType];
  if (!url) throw commandError("INVALID_INPUT", "Unsupported HKUL space facility type.");
  const tab = await chrome.tabs.create({ url, active: true });
  const snapshot = await waitForLibraryRead(tab.id, "library.spaces.read_availability", {}, Date.now() + NAVIGATION_DEADLINE_MS);
  return {
    read_only: true,
    navigation_only: true,
    library_write_requests_sent: 0,
    booking_writes_performed: 0,
    navigation_interactions_performed: true,
    target_origin: "https://booking.lib.hku.hk",
    target_page_kind: "space_availability",
    facility_type: facilityType,
    steps: ["library_fixed_route_to_space_availability"],
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
    throw commandError("COMMAND_NOT_ALLOWED", "This extension only accepts named read-only commands.");
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
