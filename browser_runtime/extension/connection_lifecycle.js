(function (root) {
  "use strict";

  const BASE_RETRY_MS = 1000;
  const MAX_RETRY_MS = 30000;

  function reconnectDelayMs(failureCount) {
    const normalized = Math.max(1, Math.min(Number(failureCount) || 1, 20));
    return Math.min(BASE_RETRY_MS * (2 ** (normalized - 1)), MAX_RETRY_MS);
  }

  function closeState(code) {
    if (code === 4401) return "token_rejected";
    if (code === 4403) return "extension_rejected";
    if (code === 4404) return "bridge_disabled";
    return "reconnecting";
  }

  function visibleState(transportState, snapshot) {
    if (transportState !== "paired") return transportState;
    if (!snapshot?.bound) return "paired";
    if (["https://hkuportal.hku.hk", "https://studentportal.hku.hk"].includes(snapshot.origin)) {
      return "portal_bound";
    }
    if (snapshot.origin === "https://sis-main.hku.hk") return "sis_bound";
    return "paired";
  }

  const api = { closeState, reconnectDelayMs, visibleState };
  root.HKUConnectionLifecycle = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
