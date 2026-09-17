(function () {
  "use strict";

  const ALLOWED_MESSAGES = new Set([
    "hku.inspect_portal",
    "portal.list_notices",
    "hku.open_sis",
    "hku.open_weekly_timetable",
    "hku.open_moodle"
  ]);

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || !ALLOWED_MESSAGES.has(message.command)) return false;
    try {
      let data;
      if (message.command === "portal.list_notices") {
        const snapshot = self.HKUNavigation.inspectPortal(document, location);
        if (snapshot.logged_in !== true) {
          const error = new Error("Complete HKU Portal login and MFA before reading notices.");
          error.code = "PORTAL_LOGIN_REQUIRED";
          throw error;
        }
        const parsed = self.HKUPortalNoticesParser.parsePortalNotices(document, location);
        data = {
          ...snapshot,
          notice_count: parsed.notices.length,
          notices: parsed.notices,
          diagnostics: parsed.diagnostics
        };
      } else if (message.command === "hku.open_sis") {
        data = self.HKUNavigation.openSisFromPortal(document, location);
      } else if (message.command === "hku.open_weekly_timetable") {
        data = self.HKUNavigation.openWeeklyTimetableFromPortal(document, location);
      } else if (message.command === "hku.open_moodle") {
        data = self.HKUNavigation.openMoodleFromPortal(document, location);
      } else {
        data = self.HKUNavigation.inspectPortal(document, location);
      }
      sendResponse({ ok: true, data });
    } catch (error) {
      sendResponse({
        ok: false,
        error: {
          code: String(error.code || "PORTAL_NAVIGATION_FAILED"),
          message: String(error.message || error)
        }
      });
    }
    return false;
  });
})();
