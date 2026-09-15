"use strict";

importScripts("connection_lifecycle.js", "browser_targets.js");

const SIS_URL_PATTERN = "https://sis-main.hku.hk/*";
const WEEKLY_TIMETABLE_URL_PATTERN = "https://sweb.hku.hk/*";
const PORTAL_URL_PATTERNS = [
  "https://hkuportal.hku.hk/*",
  "https://studentportal.hku.hk/*"
];
const SIS_ORIGIN = "https://sis-main.hku.hk";
const WEEKLY_TIMETABLE_ORIGIN = "https://sweb.hku.hk";
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
  "sis.bind_tab",
  "sis.inspect_page",
  "sis.inspect_cart",
  "sis.open_enrollment_add_classes",
  "sis.select_term",
  "sis.preflight",
  "sis.get_status",
  "timetable.inspect_weekly"
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
    return PORTAL_ORIGINS.has(origin) || origin === SIS_ORIGIN || origin === WEEKLY_TIMETABLE_ORIGIN
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
    url: [...PORTAL_URL_PATTERNS, SIS_URL_PATTERN, WEEKLY_TIMETABLE_URL_PATTERN]
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
