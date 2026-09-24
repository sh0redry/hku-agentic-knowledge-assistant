(function () {
  "use strict";
  const CONFIRM_ARM_EVENT = "hku-agents:arm-exact-library-confirm-v1";
  const CONFIRM_ARMED_EVENT = "hku-agents:exact-library-confirm-armed-v1";
  const CONFIRM_RESULT_EVENT = "hku-agents:exact-library-confirm-result-v1";
  const CONFIRM_DISARM_EVENT = "hku-agents:disarm-exact-library-confirm-v1";

  function readEventDetail(event) {
    try { return JSON.parse(String(event.detail || "")); } catch (_error) { return null; }
  }

  function submitWithExactConfirmation(payload) {
    let armed = null;
    const onArmed = event => { armed = readEventDetail(event); };
    window.addEventListener(CONFIRM_ARMED_EVENT, onArmed);
    document.dispatchEvent(new CustomEvent(CONFIRM_ARM_EVENT, {
      detail: JSON.stringify(payload?.target || {})
    }));
    window.removeEventListener(CONFIRM_ARMED_EVENT, onArmed);
    if (armed?.armed !== true) {
      const error = new Error("The exact one-use HKUL confirmation handler could not be armed; Submit was not clicked.");
      error.code = "LIBRARY_BOOKING_CONFIRM_HANDLER_UNAVAILABLE";
      throw error;
    }

    let confirmation = null;
    const onConfirmation = event => { confirmation = readEventDetail(event); };
    window.addEventListener(CONFIRM_RESULT_EVENT, onConfirmation);
    try {
      const result = self.HKULibraryParser.submitBookingOnce(
        document,
        location,
        payload?.target,
        payload?.policy_acceptance_acknowledged
      );
      if (confirmation?.dialog_seen === true && confirmation.accepted !== true) {
        const error = new Error("The HKUL confirmation dialog did not match the exact confirmed target; the dialog was rejected and no booking was submitted.");
        error.code = "LIBRARY_BOOKING_CONFIRMATION_MISMATCH";
        throw error;
      }
      return {
        ...result,
        confirmation_dialog_seen: confirmation?.dialog_seen === true,
        confirmation_dialog_accepted: confirmation?.accepted === true
      };
    } finally {
      document.dispatchEvent(new Event(CONFIRM_DISARM_EVENT));
      window.removeEventListener(CONFIRM_RESULT_EVENT, onConfirmation);
    }
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!["library.research.read_results", "library.research.read_item", "library.research.read_access_options", "library.spaces.configure_availability", "library.spaces.select_result_page", "library.spaces.read_availability", "library.spaces.select_exact_slot", "library.spaces.configure_booking_form", "library.spaces.inspect_booking_form", "library.spaces.submit_booking_once", "library.spaces.inspect_booking_confirmation", "library.spaces.accept_booking_confirmation", "library.spaces.open_booking_record", "library.spaces.read_booking_record", "library.hours.read"].includes(message?.command)) return false;
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
              ? submitWithExactConfirmation(message.payload)
            : message.command === "library.spaces.inspect_booking_confirmation"
              ? self.HKULibraryParser.bookingConfirmationDialog(document, location, message.payload?.target)
            : message.command === "library.spaces.accept_booking_confirmation"
              ? self.HKULibraryParser.acceptExactBookingConfirmation(document, location, message.payload?.target)
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
