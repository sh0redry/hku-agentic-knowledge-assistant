(function () {
  "use strict";
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!["library.research.read_results", "library.spaces.read_availability"].includes(message?.command)) return false;
    try {
      const data = message.command === "library.research.read_results"
        ? self.HKULibraryParser.parseResearch(document, location, message.payload?.limit)
        : self.HKULibraryParser.parseSpaceAvailability(document, location);
      sendResponse({ ok: true, data });
    } catch (error) {
      sendResponse({ ok: false, error: { code: String(error.code || "LIBRARY_INSPECTION_FAILED"), message: String(error.message || error) } });
    }
    return false;
  });
})();
