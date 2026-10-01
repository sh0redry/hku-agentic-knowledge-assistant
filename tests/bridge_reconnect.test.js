"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const lifecycle = require("../browser_runtime/extension/connection_lifecycle.js");
let listener; let scheduled; let timerDelay; const cleared = [];
const context = { importScripts() {}, URL, Date,
  setTimeout(_callback, delay) { timerDelay = delay; return 1; }, clearTimeout() {},
  setInterval() {}, clearInterval() {},
  HKUConnectionLifecycle: lifecycle,
  chrome: {
    storage: { local: { async get(defaults) { return defaults; } } },
    alarms: { create(name, options) { scheduled = { name, ...options }; },
      async clear(name) { cleared.push(name); }, onAlarm: { addListener(callback) { listener = callback; } } },
    runtime: { onMessage: { addListener() {} }, onStartup: { addListener() {} }, onInstalled: { addListener() {} } }
  }
};
context.self = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync("browser_runtime/extension/background.js", "utf8"), context);
vm.runInContext("reconnectAttempt = 8; scheduleReconnect();", context);
assert.equal(timerDelay, 30000);
assert.equal(scheduled.name, "hku-bridge-reconnect");
assert.ok(scheduled.when > Date.now());
// Simulate the worker waking through an alarm after its in-memory timer was lost.
vm.runInContext("var reconnectCalls = 0; connect = async () => { reconnectCalls++; };", context);
listener({ name: "unrelated" });
assert.equal(context.reconnectCalls, 0);
listener({ name: "hku-bridge-reconnect" });
assert.equal(context.reconnectCalls, 1);
vm.runInContext("restartConnection();", context);
assert.ok(cleared.includes("hku-bridge-reconnect"));
console.log("Bridge retry timer and MV3 alarm wakeup tests passed.");
