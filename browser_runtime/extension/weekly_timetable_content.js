(function () {
  "use strict";

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.command !== "timetable.inspect_weekly") return false;
    try {
      sendResponse({
        ok: true,
        data: self.HKUWeeklyTimetableParser.inspect(document, location)
      });
    } catch (error) {
      sendResponse({
        ok: false,
        error: {
          code: String(error.code || "TIMETABLE_INSPECTION_FAILED"),
          message: String(error.message || error)
        }
      });
    }
    return false;
  });
})();
