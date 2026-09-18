(function () {
  "use strict";

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (![
      "moodle.inspect_dashboard",
      "moodle.open_dashboard",
      "moodle.start_portal_sso",
      "moodle.list_courses",
      "moodle.list_upcoming_assignments"
    ].includes(message?.command)) {
      return false;
    }
    try {
      const data = message.command === "moodle.open_dashboard"
        ? self.HKUMoodleParser.openDashboard(document, location)
        : message.command === "moodle.start_portal_sso"
          ? self.HKUMoodleParser.startPortalSso(document, location)
        : message.command === "moodle.list_courses"
          ? self.HKUMoodleParser.parseCourses(document, location)
          : message.command === "moodle.list_upcoming_assignments"
            ? self.HKUMoodleParser.parseUpcomingAssignments(document, location)
          : self.HKUMoodleParser.inspect(document, location);
      sendResponse({ ok: true, data });
    } catch (error) {
      sendResponse({
        ok: false,
        error: {
          code: String(error.code || "MOODLE_INSPECTION_FAILED"),
          message: String(error.message || error)
        }
      });
    }
    return false;
  });
})();
