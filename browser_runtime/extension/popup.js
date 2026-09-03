"use strict";

const portInput = document.getElementById("port");
const tokenInput = document.getElementById("token");
const statusOutput = document.getElementById("status");

function showStatus(message, isError = false) {
  statusOutput.textContent = message;
  statusOutput.classList.toggle("error", isError);
}

async function refreshStatus() {
  const status = await chrome.runtime.sendMessage({ type: "status" });
  showStatus(`Bridge: ${status.status} · SIS tab: ${status.bound ? status.pageKind : "not bound"}`);
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
  showStatus("Pairing…");
  setTimeout(refreshStatus, 800);
});

document.getElementById("bind").addEventListener("click", async () => {
  showStatus("Looking for an open HKU SIS tab…");
  const result = await chrome.runtime.sendMessage({ type: "bind" });
  if (!result.ok) {
    showStatus(result.error.message, true);
    return;
  }
  showStatus(`Bound read-only · page: ${result.data.page_kind}`);
});

chrome.storage.local.get({ bridgePort: 7860 }).then(({ bridgePort }) => {
  portInput.value = bridgePort;
});
refreshStatus();
