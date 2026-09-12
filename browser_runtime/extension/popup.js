"use strict";

const portInput = document.getElementById("port");
const tokenInput = document.getElementById("token");
const statusOutput = document.getElementById("status");
const targetsOutput = document.getElementById("targets");

function showStatus(message, isError = false) {
  statusOutput.textContent = message;
  statusOutput.classList.toggle("error", isError);
}

async function refreshStatus() {
  const status = await chrome.runtime.sendMessage({ type: "status" });
  const retry = status.retryInSeconds > 0
    ? ` | retry in ${status.retryInSeconds}s (attempt ${status.reconnectAttempt})`
    : "";
  const detail = status.lastError ? `\n${status.lastError}` : "";
  showStatus(
    `Bridge: ${status.status} | HKU tab: ${status.bound ? status.pageKind : "not bound"}${retry}${detail}`,
    ["token_rejected", "extension_rejected", "bridge_disabled"].includes(status.status)
  );
  const targets = Array.isArray(status.targets) ? status.targets : [];
  targetsOutput.textContent = targets.length
    ? targets.map((target) =>
      `${target.system}: ${target.logged_in === true ? "authenticated" : target.logged_in === false ? "login required" : "detected"} (${target.page_kind})`
    ).join("\n")
    : "No supported HKU system tabs detected.";
}

document.getElementById("connect").addEventListener("click", async () => {
  const pairingToken = tokenInput.value.trim();
  const bridgePort = Number(portInput.value);
  if (!pairingToken || bridgePort < 1024 || bridgePort > 65535) {
    showStatus("Enter the token shown in HKU AGENTS and a valid port.", true);
    return;
  }
  await chrome.runtime.sendMessage({ type: "configure", pairingToken, bridgePort });
  tokenInput.value = "";
  showStatus("Pairing...");
  setTimeout(refreshStatus, 800);
});

document.getElementById("reconnect").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "reconnect" });
  showStatus("Reconnecting now...");
  setTimeout(refreshStatus, 300);
});

document.getElementById("bind").addEventListener("click", async () => {
  showStatus("Looking for the active HKU Portal or SIS tab...");
  const result = await chrome.runtime.sendMessage({ type: "bind" });
  if (!result.ok) {
    showStatus(result.error.message, true);
    return;
  }
  showStatus(`Bound | page: ${result.data.page_kind}`);
});

chrome.storage.local.get({ bridgePort: 7860 }).then(({ bridgePort }) => {
  portInput.value = bridgePort;
});
refreshStatus();
setInterval(refreshStatus, 1000);
