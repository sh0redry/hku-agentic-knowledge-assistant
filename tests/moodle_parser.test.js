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
assert.equal(dashboard.diagnostics.parser_version, "0.2.4");
assert.equal(dashboard.diagnostics.dashboard_marker_found, true);
assert.equal(dashboard.diagnostics.course_link_candidate_count, 0);
assert.equal(JSON.stringify(dashboard).includes("Private Course Name"), false);
assert.equal(Object.hasOwn(dashboard, "courses"), false);

function courseNode(id, name, state = "") {
  const nameNode = { textContent: `Course name ${name}` };
  const container = {
    dataset: { courseId: id, courseState: state },
    className: `dashboard-card ${state}`,
    textContent: `${name} ${state}`,
    getAttribute(attribute) {
      return attribute === "data-course-id" ? id : null;
    },
    closest(selector) {
      return selector.includes("data-course-id") ? container : null;
    },
    querySelector(selector) {
      if (selector === ".coursename") return nameNode;
      if (selector === ".sr-only") return { textContent: "Course is starred" };
      if (selector.includes("course/view.php")) return anchor;
      return null;
    }
  };
  const anchor = {
    textContent: "Course is starred",
    getAttribute(attribute) {
      return attribute === "href"
        ? `https://moodle.hku.hk/course/view.php?id=${String(id).replace(/^course-/, "")}`
        : null;
    },
    closest() { return null; }
  };
  return { container, anchor };
}

const currentCourse = courseNode("123", "COMP3297-2B Software Engineering", "current");
const pastCourse = courseNode("456", "ECON 2280 Section 1A Econometrics", "past");
const futureCourse = courseNode(
  "course-789",
  "2026-2027 FINA2320 Section 1C Investments",
  "future"
);
const emptyCourseTemplate = {
  dataset: { courseId: "" },
  textContent: "",
  getAttribute() { return ""; },
  querySelector() { return null; },
  closest(selector) {
    return selector.includes("data-course-id") ? emptyCourseTemplate : null;
  }
};
const courseDocument = {
  body: { textContent: "Dashboard Course overview Timeline Upcoming events" },
  querySelector(selector) {
    if (selector.includes(".usermenu")) return { textContent: "User menu" };
    return null;
  },
  querySelectorAll(selector) {
    if (selector === "[data-course-id]") {
      return [
        currentCourse.container,
        pastCourse.container,
        futureCourse.container,
        emptyCourseTemplate
      ];
    }
    if (selector.includes("course/view.php")) {
      return [currentCourse.anchor, pastCourse.anchor, futureCourse.anchor];
    }
    return [];
  }
};
const courseList = parser.parseCourses(courseDocument, {
  origin: "https://moodle.hku.hk",
  pathname: "/my/"
});
assert.equal(courseList.course_count, 3);
assert.deepEqual(courseList.courses[0], {
  course_id: "123",
  course_code: "COMP3297",
  section: "2B",
  academic_year: null,
  name: "COMP3297-2B Software Engineering",
  state: "current"
});
assert.equal(courseList.courses[1].course_code, "ECON2280");
assert.equal(courseList.courses[1].section, "1A");
assert.equal(courseList.courses[1].state, "past");
assert.equal(courseList.courses[2].course_id, "789");
assert.equal(courseList.courses[2].academic_year, "2026-27");
assert.equal(courseList.courses[2].state, "future");
assert.equal(courseList.diagnostics.course_candidate_count, 6);
assert.equal(courseList.diagnostics.parsed_course_count, 3);
assert.equal(courseList.diagnostics.unparsed_course_candidate_count, 0);
assert.equal(courseList.diagnostics.missing_course_id_candidate_count, 0);
assert.equal(courseList.diagnostics.missing_course_name_candidate_count, 0);
assert.equal(courseList.diagnostics.duplicate_course_candidate_count, 3);
assert.equal(courseList.diagnostics.course_placeholder_candidate_count, 1);
assert.equal(Object.hasOwn(courseList, "assignments"), false);

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
