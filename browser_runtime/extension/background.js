"use strict";

const SIS_URL_PATTERN = "https://sis-main.hku.hk/*";
const ALLOWED_COMMANDS = new Set([
  "browser.health",
  "sis.bind_tab",
  "sis.inspect_page",
  "sis.inspect_cart",
  "sis.preflight",
  "sis.get_status"
]);

let socket = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let boundTabId = null;
let lastSnapshot = null;
let bridgeStatus = "not_configured";

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
      origin: boundTabId !== null ? "https://sis-main.hku.hk" : null,
      logged_in: null,
      page_kind: "unknown",
      term_label: null,
      course_count: 0
    };
  }
  const {
    visible_courses: _visibleCourses,
    temporary_courses: _temporaryCourses,
    schedule_courses: _scheduleCourses,
    diagnostics: _diagnostics,
    ...summary
  } = lastSnapshot;
  return summary;
}

function sendHeartbeat() {
  if (socket && socket.readyState === WebSocket.OPEN && bridgeStatus === "connected") {
    socket.send(JSON.stringify({ type: "heartbeat", tab: publicTabState() }));
  }
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => connect(), 3000);
}

async function connect() {
  const settings = await loadSettings();
  if (!settings.pairingToken) {
    bridgeStatus = "not_configured";
    return;
  }
  if (socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(socket.readyState)) return;

  bridgeStatus = "connecting";
  socket = new WebSocket(websocketUrl(settings.bridgePort));
  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({
      type: "pair",
      token: settings.pairingToken,
      extension_version: chrome.runtime.getManifest().version
    }));
  });
  socket.addEventListener("message", async (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_error) {
      return;
    }
    if (message.type === "paired") {
      bridgeStatus = "connected";
      clearInterval(heartbeatTimer);
      heartbeatTimer = setInterval(sendHeartbeat, 20000);
      sendHeartbeat();
      return;
    }
    if (message.protocol_version === 1 && message.request_id && message.command) {
      await handleCommand(message);
    }
  });
  socket.addEventListener("close", () => {
    bridgeStatus = "disconnected";
    socket = null;
    clearInterval(heartbeatTimer);
    scheduleReconnect();
  });
  socket.addEventListener("error", () => {
    bridgeStatus = "error";
  });
}

async function findSisTab() {
  const tabs = await chrome.tabs.query({ url: SIS_URL_PATTERN });
  if (!tabs.length) throw commandError("SIS_TAB_NOT_FOUND", "Open HKU SIS in Chrome first.");
  tabs.sort((left, right) => Number(right.active) - Number(left.active));
  return tabs[0];
}

async function inspectBoundTab(command) {
  let tab;
  if (boundTabId !== null) {
    try {
      tab = await chrome.tabs.get(boundTabId);
    } catch (_error) {
      boundTabId = null;
    }
  }
  if (!tab || !tab.url || !tab.url.startsWith("https://sis-main.hku.hk/")) {
    tab = await findSisTab();
    boundTabId = tab.id;
  }
  try {
    const response = await chrome.tabs.sendMessage(boundTabId, { command });
    if (!response || !response.ok) {
      throw commandError(
        response?.error?.code || "PAGE_SCRIPT_UNAVAILABLE",
        response?.error?.message || "Reload the HKU SIS tab after installing the extension."
      );
    }
    lastSnapshot = response.data;
    sendHeartbeat();
    return response.data;
  } catch (error) {
    if (error.code) throw error;
    throw commandError("PAGE_SCRIPT_UNAVAILABLE", "Reload the HKU SIS tab and try again.");
  }
}

function commandError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

async function executeCommand(command) {
  if (!ALLOWED_COMMANDS.has(command)) {
    throw commandError("COMMAND_NOT_ALLOWED", "This extension only accepts named read-only commands.");
  }
  if (command === "browser.health") {
    return { connected: bridgeStatus === "connected", read_only: true };
  }
  if (command === "sis.bind_tab") {
    const tab = await findSisTab();
    boundTabId = tab.id;
    return inspectBoundTab("sis.inspect_page");
  }
  if (command === "sis.preflight") return inspectBoundTab("sis.inspect_cart");
  return inspectBoundTab(command);
}

async function handleCommand(message) {
  const response = { protocol_version: 1, request_id: message.request_id, ok: false, data: {} };
  try {
    response.data = await executeCommand(message.command);
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
      if (socket) socket.close();
      connect();
      sendResponse({ ok: true });
    });
    return true;
  }
  if (message?.type === "status") {
    sendResponse({
      status: bridgeStatus,
      bound: boundTabId !== null,
      pageKind: lastSnapshot?.page_kind || "unknown"
    });
    return false;
  }
  if (message?.type === "bind") {
    executeCommand("sis.bind_tab")
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
