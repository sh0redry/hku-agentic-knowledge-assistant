"use strict";

const assert = require("node:assert/strict");
const lifecycle = require("../browser_runtime/extension/connection_lifecycle.js");

assert.deepEqual(
  [1, 2, 3, 4, 5, 6, 20].map(lifecycle.reconnectDelayMs),
  [1000, 2000, 4000, 8000, 16000, 30000, 30000]
);

assert.equal(lifecycle.closeState(4401), "token_rejected");
assert.equal(lifecycle.closeState(4403), "extension_rejected");
assert.equal(lifecycle.closeState(4404), "bridge_disabled");
assert.equal(lifecycle.closeState(1006), "reconnecting");

assert.equal(lifecycle.visibleState("not_configured", null), "not_configured");
assert.equal(lifecycle.visibleState("connecting", null), "connecting");
assert.equal(lifecycle.visibleState("paired", null), "paired");
assert.equal(
  lifecycle.visibleState("paired", {
    bound: true,
    origin: "https://studentportal.hku.hk"
  }),
  "portal_bound"
);
assert.equal(
  lifecycle.visibleState("paired", {
    bound: true,
    origin: "https://sis-main.hku.hk"
  }),
  "sis_bound"
);

console.log("Browser connection lifecycle synthetic tests passed.");
