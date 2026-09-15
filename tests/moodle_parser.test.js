"use strict";

const assert = require("node:assert/strict");
const parser = require("../browser_runtime/extension/moodle_parser.js");

function dashboardDocument() {
  return {
    body: {
      textContent: "Dashboard Course overview Timeline Upcoming events Private Course Name"
    },
    querySelector(selector) {
      if (selector.includes(".usermenu")) return { textContent: "User menu" };
      return null;
    },
    querySelectorAll(selector) {
      if (selector === "a[href*='/course/view.php']") return [{}, {}, {}];
      return [];
    }
  };
}

const dashboard = parser.inspect(dashboardDocument(), {
  origin: "https://moodle.hku.hk",
  pathname: "/my/"
});
assert.equal(dashboard.logged_in, true);
assert.equal(dashboard.page_kind, "dashboard");
assert.equal(dashboard.diagnostics.parser_version, "0.1.0");
assert.equal(dashboard.diagnostics.dashboard_marker_found, true);
assert.equal(dashboard.diagnostics.course_link_candidate_count, 3);
assert.equal(JSON.stringify(dashboard).includes("Private Course Name"), false);
assert.equal(Object.hasOwn(dashboard, "courses"), false);

const homeLocation = {
  origin: "https://moodle.hku.hk",
  pathname: "/",
  assigned: [],
  assign(url) { this.assigned.push(url); }
};
const homeNavigation = parser.openDashboard(dashboardDocument(), homeLocation);
assert.equal(homeNavigation.navigation_started, true);
assert.deepEqual(homeLocation.assigned, ["https://moodle.hku.hk/my/"]);

const dashboardLocation = {
  origin: "https://moodle.hku.hk",
  pathname: "/my/",
  assigned: [],
  assign(url) { this.assigned.push(url); }
};
const dashboardNavigation = parser.openDashboard(dashboardDocument(), dashboardLocation);
assert.equal(dashboardNavigation.navigation_started, false);
assert.deepEqual(dashboardLocation.assigned, []);

const login = parser.inspect({
  body: { textContent: "Log in to the site HKU Portal User login" },
  querySelector() { return null; },
  querySelectorAll() { return []; }
}, {
  origin: "https://moodle.hku.hk",
  pathname: "/login/index.php"
});
assert.equal(login.logged_in, false);
assert.equal(login.page_kind, "login");
assert.equal(login.diagnostics.login_marker_found, true);
assert.throws(
  () => parser.openDashboard({
    body: { textContent: "HKU Portal User login" },
    querySelector() { return null; },
    querySelectorAll() { return []; }
  }, {
    origin: "https://moodle.hku.hk",
    pathname: "/login/index.php",
    assign() { throw new Error("must not navigate"); }
  }),
  error => error.code === "MOODLE_LOGIN_REQUIRED"
);

assert.throws(
  () => parser.inspect(dashboardDocument(), { origin: "https://evil.example", pathname: "/my/" }),
  error => error.code === "WRONG_MOODLE_ORIGIN"
);

console.log("HKU Moodle diagnostic parser tests passed.");
