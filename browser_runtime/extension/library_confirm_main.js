(function (root) {
  "use strict";

  const ARM_EVENT = "hku-agents:arm-exact-library-confirm-v1";
  const ARMED_EVENT = "hku-agents:exact-library-confirm-armed-v1";
  const RESULT_EVENT = "hku-agents:exact-library-confirm-result-v1";
  const DISARM_EVENT = "hku-agents:disarm-exact-library-confirm-v1";

  function clean(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function matchesBookingConfirmation(message, target) {
    const text = clean(message);
    const facilityType = clean(target?.booking_facility_type);
    const facility = clean(target?.room);
    const date = clean(target?.date);
    const start = clean(target?.start_time);
    const end = clean(target?.end_time);
    if (!text || !facilityType || !facility || !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
        !/^\d{2}:\d{2}$/.test(start) || !/^\d{2}:\d{2}$/.test(end) ||
        !/please confirm (?:the )?following booking/i.test(text)) return false;

    return new RegExp(`\\bFacility\\s*Type\\s*:\\s*${escapeRegExp(facilityType)}(?=\\s+Facility\\s*:)`, "i").test(text) &&
      new RegExp(`\\bFacility\\s*:\\s*${escapeRegExp(facility)}(?=\\s+Date\\s*:)`, "i").test(text) &&
      new RegExp(`\\bDate\\s*:\\s*${escapeRegExp(date)}(?:\\s+\\([A-Za-z]{3,9}\\))?(?=\\s+Session\\s*:)`, "i").test(text) &&
      new RegExp(`\\bSession\\s*:\\s*${escapeRegExp(start)}\\s*-\\s*${escapeRegExp(end)}$`, "i").test(text);
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { matchesBookingConfirmation };
    return;
  }

  const documentObject = root.document;
  if (!documentObject || typeof root.confirm !== "function") return;
  let active = null;

  function emit(name, value) {
    root.dispatchEvent(new root.CustomEvent(name, { detail: JSON.stringify(value) }));
  }

  function restore(record) {
    if (!record) return;
    if (record.timer) root.clearTimeout(record.timer);
    if (root.confirm === record.wrapper) {
      try { root.confirm = record.original; } catch (_error) { /* Keep the page safe if the property is locked. */ }
    }
    if (active === record) active = null;
  }

  documentObject.addEventListener(ARM_EVENT, (event) => {
    restore(active);
    let target = null;
    try { target = JSON.parse(String(event.detail || "")); } catch (_error) { target = null; }
    const original = root.confirm;
    if (!target || typeof original !== "function") {
      emit(ARMED_EVENT, { armed: false });
      return;
    }

    const record = { target, original, wrapper: null, timer: null };
    record.wrapper = function (message) {
      if (active !== record) return original.call(root, message);
      restore(record);
      const accepted = matchesBookingConfirmation(message, target);
      emit(RESULT_EVENT, { dialog_seen: true, accepted });
      // A mismatch is rejected locally. Never fall through to an unverified modal.
      return accepted;
    };
    active = record;
    try { root.confirm = record.wrapper; } catch (_error) { restore(record); }
    if (root.confirm !== record.wrapper) {
      restore(record);
      emit(ARMED_EVENT, { armed: false });
      return;
    }
    record.timer = root.setTimeout(() => restore(record), 5000);
    emit(ARMED_EVENT, { armed: true });
  });

  documentObject.addEventListener(DISARM_EVENT, () => restore(active));
})(globalThis);
