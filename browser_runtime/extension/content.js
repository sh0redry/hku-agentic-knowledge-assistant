(function () {
  "use strict";

  const ALLOWED_MESSAGES = new Set([
    "sis.inspect_page",
    "sis.inspect_cart",
    "sis.get_status",
    "sis.open_enrollment_add_classes",
    "sis.select_term"
  ]);

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || !ALLOWED_MESSAGES.has(message.command)) return false;
    try {
      let data;
      if (message.command === "sis.open_enrollment_add_classes") {
        data = self.HKUNavigation.openEnrollmentAddClasses(
            document,
            location,
            self.HKUSISParser.inspect
          );
      } else if (message.command === "sis.select_term") {
        data = self.HKUNavigation.selectTerm(
          document,
          location,
          message.payload?.term_label,
          self.HKUSISParser.inspect
        );
      } else {
        data = self.HKUSISParser.inspect(document, location);
      }
      sendResponse({ ok: true, data });
    } catch (error) {
      sendResponse({
        ok: false,
        error: {
          code: String(error.code || "PAGE_INSPECTION_FAILED"),
          message: String(error.message || error)
        }
      });
    }
    return false;
  });
})();
