(function () {
  "use strict";
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!["library.research.read_results", "library.research.read_item", "library.research.read_access_options", "library.spaces.configure_availability", "library.spaces.select_result_page", "library.spaces.read_availability", "library.spaces.select_exact_slot", "library.spaces.configure_booking_form", "library.spaces.inspect_booking_form", "library.spaces.submit_booking_once", "library.spaces.open_booking_record", "library.spaces.read_booking_record", "library.hours.read"].includes(message?.command)) return false;
    try {
      const data = message.command === "library.research.read_results"
        ? self.HKULibraryParser.parseResearch(document, location, message.payload?.limit)
        : message.command.startsWith("library.research.read_")
          ? self.HKULibraryParser.parseResearchDetail(document, location)
          : message.command === "library.hours.read"
            ? self.HKULibraryParser.parseHoursAndLocations(document, location)
            : message.command === "library.spaces.configure_availability"
              ? self.HKULibraryParser.configureSpaceAvailability(document, location, message.payload)
            : message.command === "library.spaces.select_result_page"
              ? self.HKULibraryParser.selectSpaceResultPage(document, location, message.payload)
            : message.command === "library.spaces.select_exact_slot"
              ? self.HKULibraryParser.clickExactAvailableSlot(document, location, message.payload?.target)
            : message.command === "library.spaces.configure_booking_form"
              ? self.HKULibraryParser.configureBookingForm(document, location, message.payload?.target)
            : message.command === "library.spaces.inspect_booking_form"
              ? self.HKULibraryParser.inspectBookingForm(document, location, message.payload?.target)
            : message.command === "library.spaces.submit_booking_once"
              ? self.HKULibraryParser.submitBookingOnce(document, location, message.payload?.target)
            : message.command === "library.spaces.open_booking_record"
              ? self.HKULibraryParser.openBookingRecord(document, location)
            : message.command === "library.spaces.read_booking_record"
              ? self.HKULibraryParser.verifyBookingRecord(document, location, message.payload?.target)
            : self.HKULibraryParser.parseSpaceAvailability(document, location);
      sendResponse({ ok: true, data });
    } catch (error) {
      sendResponse({ ok: false, error: { code: String(error.code || "LIBRARY_INSPECTION_FAILED"), message: String(error.message || error) } });
    }
    return false;
  });
})();
