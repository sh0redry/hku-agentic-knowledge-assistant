(function () {
  "use strict";

  const ALLOWED_MESSAGES = new Set([
    "hku.inspect_portal",
    "hku.open_sis"
  ]);

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || !ALLOWED_MESSAGES.has(message.command)) return false;
    try {
      let data;
      if (message.command === "hku.open_sis") {
        data = self.HKUNavigation.openSisFromPortal(document, location);
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
