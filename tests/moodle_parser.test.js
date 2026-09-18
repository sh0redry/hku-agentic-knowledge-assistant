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
assert.equal(dashboard.diagnostics.parser_version, "0.4.1");
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

function assignmentNode({ eventId, moduleId, courseId, title, courseName, timestamp, type, source }) {
  const activityAnchor = {
    textContent: title,
    getAttribute(attribute) {
      return attribute === "href"
        ? `https://moodle.hku.hk/mod/${type}/view.php?id=${moduleId}`
        : null;
    }
  };
  const courseAnchor = {
    textContent: courseName,
    getAttribute(attribute) {
      return attribute === "href"
        ? `https://moodle.hku.hk/course/view.php?id=${courseId}`
        : null;
    }
  };
  return {
    dataset: {
      eventId,
      courseId,
      timeSort: String(timestamp),
      activityType: type
    },
    textContent: `${title} ${courseName}`,
    getAttribute(attribute) {
      const values = {
        "data-event-id": eventId,
        "data-course-id": courseId,
        "data-time-sort": String(timestamp),
        "data-activity-type": type
      };
      return values[attribute] || null;
    },
    querySelector(selector) {
      if (selector.includes("a[href*='/mod/']")) return activityAnchor;
      if (selector === "[data-region='event-name']") return { textContent: title };
      if (selector === "[data-region='course-name']") return { textContent: courseName };
      if (selector.includes("course/view.php")) return courseAnchor;
      return null;
    },
    closest(selector) {
      return selector === ".block_calendar_upcoming" && source === "upcoming" ? {} : null;
    }
  };
}

const assignment = assignmentNode({
  eventId: "9001",
  moduleId: "7001",
  courseId: "123",
  title: "Project milestone",
  courseName: "COMP3297 Software Engineering",
  timestamp: 4102444800,
  type: "assign",
  source: "timeline"
});
const quiz = assignmentNode({
  eventId: "9002",
  moduleId: "7002",
  courseId: "456",
  title: "Week 3 quiz",
  courseName: "ECON2280 Econometrics",
  timestamp: 4102531200,
  type: "quiz",
  source: "upcoming"
});
const noActivities = {
  textContent: "No upcoming activities due",
  querySelector() { return null; },
  closest() { return null; }
};
const dataOnlyAssignment = {
  dataset: {
    eventId: "9003",
    eventCourseid: "789",
    eventTimestart: "4102617600",
    eventComponent: "mod_assign",
    eventInstance: "7003",
    eventName: "Dataset-only deadline",
    eventUrl: "https://moodle.hku.hk/mod/assign/view.php?id=7003",
    eventCoursename: "FINA2330 Financial Markets"
  },
  textContent: "Dataset-only deadline",
  getAttribute() { return null; },
  querySelector() { return null; },
  closest() { return null; }
};
const assignmentDocument = {
  body: { textContent: "Dashboard Course overview Timeline Upcoming events" },
  querySelector(selector) {
    if (selector.includes(".usermenu")) return { textContent: "User menu" };
    return null;
  },
  querySelectorAll(selector) {
    if (selector === "[data-region='event-list-item']") {
      return [assignment, quiz, dataOnlyAssignment, noActivities];
    }
    if (selector === "[data-event-id]") return [assignment, quiz, dataOnlyAssignment];
    return [];
  }
};
const assignmentList = parser.parseUpcomingAssignments(assignmentDocument, {
  origin: "https://moodle.hku.hk",
  pathname: "/my/"
});
assert.equal(assignmentList.assignment_count, 3);
assert.deepEqual(assignmentList.assignments[0], {
  event_id: "9001",
  module_id: "7001",
  course_id: "123",
  course_name: "COMP3297 Software Engineering",
  title: "Project milestone",
  activity_type: "assignment",
  due_at: "2100-01-01T00:00:00.000Z",
  due_at_source: "machine",
  source: "timeline"
});
assert.equal(assignmentList.assignments[1].activity_type, "quiz");
assert.equal(assignmentList.assignments[1].source, "upcoming");
assert.equal(assignmentList.assignments[2].module_id, "7003");
assert.equal(assignmentList.assignments[2].course_id, "789");
assert.equal(assignmentList.assignments[2].activity_type, "assignment");
assert.equal(assignmentList.diagnostics.assignment_candidate_count, 3);
assert.equal(assignmentList.diagnostics.parsed_assignment_count, 3);
assert.equal(assignmentList.diagnostics.unparsed_assignment_candidate_count, 0);
assert.equal(assignmentList.diagnostics.assignment_placeholder_candidate_count, 1);
assert.equal(assignmentList.diagnostics.parsed_assignment_display_date_count, 0);
assert.equal(Object.hasOwn(assignmentList.assignments[0], "submission_status"), false);

assert.equal(
  parser.parseMoodleDisplayDate(
    "Due: Thursday, 17 September 2026, 11:59 PM",
    new Date("2026-09-17T00:00:00Z")
  ),
  "2026-09-17T15:59:00.000Z"
);
assert.equal(
  parser.parseMoodleDisplayDate(
    "Tomorrow, 09:30 AM",
    new Date("2026-09-17T12:00:00Z")
  ),
  "2026-09-18T01:30:00.000Z"
);
assert.equal(parser.parseMoodleDisplayDate("sometime next week"), null);
assert.equal(
  parser.parseMoodleDisplayDate(
    "Thursday, 17 September, 11:59 PM",
    new Date("2026-09-16T00:00:00.000Z")
  ),
  "2026-09-17T15:59:00.000Z"
);

const displayDateRow = {
  dataset: { eventId: "9010", eventName: "Essay deadline" },
  textContent: "Essay deadline Due: Thursday, 17 September 2026, 11:59 PM",
  getAttribute() { return null; },
  querySelector(selector) {
    if (selector === "[data-region='event-name']") return { textContent: "Essay deadline" };
    if (selector === "[data-region='event-time']") {
      return {
        textContent: "Due: Thursday, 17 September 2026, 11:59 PM",
        getAttribute() { return null; }
      };
    }
    return null;
  },
  closest() { return null; }
};
const displayDateDocument = {
  body: { textContent: "Dashboard Course overview Timeline Upcoming events" },
  querySelector(selector) {
    if (selector.includes(".usermenu")) return { textContent: "User menu" };
    return null;
  },
  querySelectorAll(selector) {
    return selector === "[data-region='event-list-item']" ? [displayDateRow] : [];
  }
};
const displayDateList = parser.parseUpcomingAssignments(displayDateDocument, {
  origin: "https://moodle.hku.hk",
  pathname: "/my/"
});
assert.equal(displayDateList.assignment_count, 1);
assert.equal(displayDateList.assignments[0].due_at, "2026-09-17T15:59:00.000Z");
assert.equal(displayDateList.assignments[0].due_at_source, "display_text_hong_kong");
assert.equal(displayDateList.diagnostics.parsed_assignment_display_date_count, 1);

const groupedDate = { textContent: "Thursday, 17 September" };
const groupedDateContainer = {
  querySelector(selector) {
    return selector === "[data-region='event-list-group-date'], h4, h5" ? groupedDate : null;
  }
};
const groupedDateRow = {
  dataset: { eventId: "9011", eventName: "Quiz closes" },
  textContent: "Quiz closes 11:59 PM",
  getAttribute() { return null; },
  querySelector(selector) {
    if (selector === "[data-region='event-name']") return { textContent: "Quiz closes" };
    if (selector === "[data-region='event-time']") {
      return { textContent: "11:59 PM", getAttribute() { return null; } };
    }
    return null;
  },
  closest(selector) {
    return selector.includes("event-list-group") ? groupedDateContainer : null;
  }
};
const groupedDateDocument = {
  body: { textContent: "Dashboard Course overview Timeline Upcoming events" },
  querySelector(selector) {
    if (selector.includes(".usermenu")) return { textContent: "User menu" };
    return null;
  },
  querySelectorAll(selector) {
    return selector === "[data-region='event-list-item']" ? [groupedDateRow] : [];
  }
};
const groupedDateList = parser.parseUpcomingAssignments(groupedDateDocument, {
  origin: "https://moodle.hku.hk",
  pathname: "/my/"
});
assert.equal(groupedDateList.assignment_count, 1);
assert.equal(
  groupedDateList.assignments[0].due_at_source,
  "display_text_hong_kong_inferred_year"
);
assert.equal(groupedDateList.diagnostics.inferred_assignment_year_count, 1);

const splitExplicitDateRow = {
  dataset: { eventId: "9012", eventName: "Project deadline" },
  textContent: "Project deadline",
  getAttribute() { return null; },
  querySelector(selector) {
    if (selector === "[data-region='event-name']") return { textContent: "Project deadline" };
    if (selector === "[data-region='event-time']") {
      return { textContent: "23:59", getAttribute() { return null; } };
    }
    if (selector === "[data-region='event-date']") {
      return { textContent: "Thursday, 17 September 2026", getAttribute() { return null; } };
    }
    return null;
  },
  closest() { return null; }
};
const splitExplicitDateDocument = {
  body: { textContent: "Dashboard Course overview Timeline Upcoming events" },
  querySelector(selector) {
    if (selector.includes(".usermenu")) return { textContent: "User menu" };
    return null;
  },
  querySelectorAll(selector) {
    return selector === "[data-region='event-list-item']" ? [splitExplicitDateRow] : [];
  }
};
const splitExplicitDateList = parser.parseUpcomingAssignments(splitExplicitDateDocument, {
  origin: "https://moodle.hku.hk",
  pathname: "/my/"
});
assert.equal(splitExplicitDateList.assignment_count, 1);
assert.equal(splitExplicitDateList.assignments[0].due_at, "2026-09-17T15:59:00.000Z");
assert.equal(
  splitExplicitDateList.assignments[0].due_at_source,
  "display_text_hong_kong_combined_fragments"
);
assert.equal(
  splitExplicitDateList.diagnostics.combined_assignment_date_fragments_parsed_count,
  1
);

function todoCard(moduleId, title, dateText) {
  const row = {
    textContent: `${title} ${dateText}`,
    parentElement: null,
    getAttribute() { return null; },
    querySelector(selector) {
      return selector.includes("/mod/") || selector.includes("mod/") ? anchor : null;
    },
    closest() { return null; }
  };
  const anchor = {
    textContent: title,
    parentElement: row,
    getAttribute(attribute) {
      return attribute === "href"
        ? `https://moodle.hku.hk/mod/assign/view.php?id=${moduleId}`
        : null;
    },
    querySelector() { return null; },
    closest() { return null; }
  };
  return { row, anchor };
}
const todoPrimary = todoCard(
  "8123",
  "Assignment 1 (Due on 27 SEP SUNDAY, 23:59) is due",
  "Sunday, 27 September 2026, 11:59 PM"
);
const todoDuplicate = todoCard(
  "8123",
  "Assignment 1 (Due on 27 S...) is due",
  "Sunday, 27 September 2026, 11:59 PM"
);
const todoDocument = {
  body: { textContent: "Dashboard To do Recently accessed courses Calendar" },
  querySelector(selector) {
    if (selector.includes(".usermenu")) return { textContent: "User menu" };
    return null;
  },
  querySelectorAll(selector) {
    return selector.includes("/mod/") || selector.includes("mod/")
      ? [todoPrimary.anchor, todoDuplicate.anchor]
      : [];
  }
};
const todoList = parser.parseUpcomingAssignments(todoDocument, {
  origin: "https://moodle.hku.hk",
  pathname: "/my/"
});
assert.equal(todoList.diagnostics.todo_marker_found, true);
assert.equal(todoList.diagnostics.assignment_candidate_count, 2);
assert.equal(todoList.assignment_count, 1);
assert.equal(todoList.diagnostics.duplicate_assignment_candidate_count, 1);
assert.equal(todoList.assignments[0].module_id, "8123");
assert.equal(todoList.assignments[0].source, "todo");
assert.equal(todoList.assignments[0].due_at, "2026-09-27T15:59:00.000Z");

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
assert.equal(login.diagnostics.sso_entry_available, false);

let queuedSsoNavigation = null;
const portalSsoControl = {
  tagName: "A",
  textContent: "HKU Portal user login",
  clicked: 0,
  getAttribute(name) {
    if (name === "href") return "javascript:void(0)";
    if (name === "aria-label") return "Sign in";
    return null;
  },
  click() { this.clicked += 1; }
};
const ssoLoginDocument = {
  body: { textContent: "Log in to the site HKU Portal User" },
  querySelector() { return null; },
  querySelectorAll(selector) {
    return selector.includes("button") ? [portalSsoControl] : [];
  }
};
const ssoLoginLocation = {
  origin: "https://moodle.hku.hk",
  pathname: "/login/index.php",
  href: "https://moodle.hku.hk/login/index.php"
};
const ssoStart = parser.startPortalSso(
  ssoLoginDocument,
  ssoLoginLocation,
  action => { queuedSsoNavigation = action; }
);
assert.equal(ssoStart.sso_interaction_performed, true);
assert.equal(ssoStart.credentials_entered, false);
assert.equal(ssoStart.mfa_interactions_performed, false);
assert.equal(portalSsoControl.clicked, 0);
queuedSsoNavigation();
assert.equal(portalSsoControl.clicked, 1);

assert.throws(
  () => parser.startPortalSso({
    body: { textContent: "Log in to the site Password" },
    querySelector(selector) {
      return selector === "input[type='password']" ? {} : null;
    },
    querySelectorAll() { return []; }
  }, ssoLoginLocation),
  error => error.code === "MOODLE_SSO_ENTRY_NOT_FOUND"
);
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
