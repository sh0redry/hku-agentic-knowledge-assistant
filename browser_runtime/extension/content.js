(function () {
  "use strict";

  const ALLOWED_MESSAGES = new Set(["sis.inspect_page", "sis.inspect_cart", "sis.get_status"]);

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || !ALLOWED_MESSAGES.has(message.command)) return false;
    try {
      const snapshot = self.HKUSISParser.inspect(document, location);
      sendResponse({ ok: true, data: snapshot });
    } catch (error) {
      sendResponse({
        ok: false,
        error: { code: "PAGE_INSPECTION_FAILED", message: String(error.message || error) }
      });
    }
    return false;
  });
})();
