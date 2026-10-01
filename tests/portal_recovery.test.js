"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("browser_runtime/extension/background.js", "utf8");
let created = 0;
let loginRequired = false;
let portalVisible = false;
let portalReads = 0;
const commands = [];
const context = {
  importScripts() {}, URL, Date, console, setTimeout, clearTimeout, setInterval, clearInterval,
  chrome: {
    alarms: { create() {}, async clear() {}, onAlarm: { addListener() {} } },
    storage: { local: { async get(d) { return d; } } },
    runtime: { onMessage: { addListener() {} }, onStartup: { addListener() {} }, onInstalled: { addListener() {} } },
    tabs: {
      async query() { return portalVisible ? [{ id: 9, url: "https://studentportal.hku.hk/", active: true }] : []; },
      async create(options) {
        assert.equal(options.url, "https://hkuportal.hku.hk/");
        created++;
        return { id: 9, url: options.url };
      },
      async get() { return { id: 9, url: "https://studentportal.hku.hk/" }; },
      async sendMessage(id, message) {
        commands.push(message.command);
        if (message.command === "hku.inspect_portal") {
          portalReads++;
          return { ok: true, data: { origin: "https://studentportal.hku.hk", logged_in: !loginRequired,
            page_kind: loginRequired ? "portal_login" : "portal_home" } };
        }
        if (message.command === "portal.list_notices") return { ok: true, data: { notice_count: 2 } };
        return { ok: true, data: { portal_sso_entry_clicked: true } };
      }
    }
  }
};
context.self = context;
vm.createContext(context);
vm.runInContext(source, context);
const run = code => vm.runInContext(code, context);
(async () => {
  // Portal was replaced by timetable. Recover in a separate fixed-origin tab.
  await run("requireAuthenticatedPortalTab()");
  assert.equal(created, 1);
  await run("requireAuthenticatedPortalTab()");
  assert.equal(created, 1, "reuse recovery tab, do not create on each call");
  portalVisible = true;
  await run("requireAuthenticatedPortalTab()");
  assert.equal(created, 1);
  await run("readPortalNotices()");
  assert.ok(commands.includes("portal.list_notices"));
  // Inspect Portal must not return the currently bound timetable snapshot.
  await run('inspectBoundHkuTab = async () => ({origin:"https://sweb.hku.hk", logged_in:true, page_kind:"weekly_timetable"}); sendHeartbeat = async () => {};');
  assert.equal((await run('executeCommand("hku.inspect_portal")')).page_kind, "portal_home");
  await run('findAuthenticatedMoodleSnapshot = async () => null; waitForMoodleDashboardSnapshot = async () => ({snapshot:{origin:"https://moodle.hku.hk", logged_in:true, page_kind:"dashboard"}});');
  const moodle = await run("openMoodleDashboard()");
  assert.equal(moodle.snapshot.page_kind, "dashboard");
  assert.ok(commands.includes("hku.open_moodle"));
  // Target sessions must work without any Portal dependency.
  await run('findAuthenticatedSisSnapshot = async () => ({origin:"https://sis-main.hku.hk",logged_in:true});');
  const before = portalReads;
  await run("openSisOutcome()");
  assert.equal(portalReads, before);
  await run('inspectBoundHkuTab = async () => ({origin:"https://moodle.hku.hk",logged_in:true,page_kind:"dashboard"}); findAuthenticatedWeeklyTimetableSnapshot = async () => ({origin:"https://sweb.hku.hk",logged_in:true,page_kind:"weekly_timetable"});');
  assert.equal((await run("openWeeklyTimetable()")).steps[0], "weekly_timetable_tab_reused");
  assert.equal(portalReads, before);
  await run('findAuthenticatedMoodleSnapshot = async () => ({origin:"https://moodle.hku.hk",logged_in:true,page_kind:"dashboard"}); inspectBoundHkuTab = async () => ({origin:"https://sweb.hku.hk",logged_in:true,page_kind:"weekly_timetable"});');
  assert.equal((await run("openMoodleDashboard()")).moodle_session_reused, true);
  assert.equal(portalReads, before);
  // A genuinely expired session stops: no credential/MFA commands.
  await run('inspectBoundHkuTab = async () => ({origin:"https://moodle.hku.hk",logged_in:true,page_kind:"dashboard"}); findAuthenticatedWeeklyTimetableSnapshot = async () => null; waitForWeeklyTimetableSnapshot = async () => ({origin:"https://sweb.hku.hk",logged_in:true,page_kind:"weekly_timetable"});');
  assert.equal((await run("openWeeklyTimetable()")).steps[0], "portal_to_weekly_timetable");
  assert.ok(commands.includes("hku.open_weekly_timetable"));
  await run('findAuthenticatedSisSnapshot = async () => null; querySisTabs = async () => []; waitForSisSnapshot = async () => ({origin:"https://sis-main.hku.hk",logged_in:true,page_kind:"cart",term_label:"test"});');
  const sis = await run('openEnrollmentAddClasses("test")');
  assert.ok(sis.steps.includes("portal_to_sis"));
  assert.ok(commands.includes("hku.open_sis"));
  loginRequired = true;
  await assert.rejects(run("requireAuthenticatedPortalTab()"), e => e.code === "PORTAL_LOGIN_REQUIRED");
  assert.ok(commands.every(c => ["hku.inspect_portal", "portal.list_notices", "hku.open_moodle", "hku.open_weekly_timetable", "hku.open_sis"].includes(c)));
  console.log("Portal recovery and cross-system session regression tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
