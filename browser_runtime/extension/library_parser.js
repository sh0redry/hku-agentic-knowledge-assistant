(function (root) {
  "use strict";

  const PRIMO_ORIGIN = "https://julac-hku.primo.exlibrisgroup.com";
  const LIBRARY_ORIGIN = "https://lib.hku.hk";
  const BOOKING_ORIGIN = "https://booking.lib.hku.hk";
  const VERSION = "0.3.5";
  const HOURS_VERSION = "0.1.1";
  const BOOKING_FORM_VERSION = "0.1.0";

  function clean(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function safeDetailUrl(href) {
    try {
      const url = new URL(href, PRIMO_ORIGIN);
      const docid = url.searchParams.get("docid") || "";
      if (url.origin !== PRIMO_ORIGIN || url.pathname !== "/discovery/fulldisplay" ||
          !/^[A-Za-z0-9_.:-]{3,120}$/.test(docid)) return null;
      const safe = new URL("/discovery/fulldisplay", PRIMO_ORIGIN);
      safe.searchParams.set("docid", docid);
      safe.searchParams.set("vid", "852JULAC_HKU:HKU");
      safe.searchParams.set("lang", "en");
      return safe.toString();
    } catch (_error) {
      return null;
    }
  }

  function resultNodes(documentObject) {
    try {
      return [...documentObject.querySelectorAll("[id^='SEARCH_RESULT_RECORDID_']")];
    } catch (_error) {
      return [];
    }
  }

  function textLines(node) {
    return String(node?.innerText || node?.textContent || "")
      .split(/\n+/)
      .map((value) => clean(value).replace(/^,?\s*opens in a new window\s*$/i, ""))
      .filter(Boolean);
  }

  function usableTitle(value) {
    const title = clean(value);
    if (!title || /^(?:view|open|show|details?|full display(?: page)?|view full display(?: details?)?|find@hkul|loading(?:\.\.\.)?)$/i.test(title)) return null;
    return title;
  }

  function titleFromLines(lines) {
    const typeIndex = lines.findIndex((line) => /^(?:book|journal|article|audio cd|video|newspaper article|book chapter|multiple versions)$/i.test(line));
    const candidates = typeIndex >= 0 ? lines.slice(typeIndex + 1) : lines;
    return candidates.find((line) =>
      usableTitle(line) &&
      !/^\d+$/.test(line) &&
      !/^(?:citation|e-mail|add item|show actions|online access|available at|checked out|view journal contents)/i.test(line)
    ) || null;
  }

  function parseResearch(documentObject, locationObject, limit = 10) {
    if (locationObject?.origin !== PRIMO_ORIGIN) {
      const error = new Error("Open Find@HKUL before reading research results.");
      error.code = "WRONG_LIBRARY_PAGE";
      throw error;
    }
    const path = String(locationObject?.pathname || "").toLowerCase();
    if (!path.startsWith("/discovery/search")) {
      const error = new Error("Find@HKUL search results are not open.");
      error.code = "LIBRARY_SEARCH_NOT_READY";
      throw error;
    }
    const candidates = resultNodes(documentObject);
    const results = [];
    let unsafe = 0;
    let incomplete = 0;
    let missingRecordId = 0;
    let missingTitle = 0;
    let missingDetailUrl = 0;
    for (const node of candidates.slice(0, Math.max(1, Math.min(Number(limit) || 10, 20)))) {
      const idMatch = String(node.id || "").match(/^SEARCH_RESULT_RECORDID_(.+)$/);
      const anchor = node.querySelector?.(
        "h3 a[href*='/discovery/fulldisplay'], a[href*='/discovery/fulldisplay'], " +
        "a[ng-href*='/discovery/fulldisplay'], a[href*='fulldisplay?']"
      ) || null;
      const titleNode = node.querySelector?.(
        "[class*='item-title'], [class*='item_title'], [data-field-selector='title'], h3, h2"
      ) || null;
      const lines = textLines(node);
      const title = usableTitle(anchor?.innerText) || usableTitle(anchor?.textContent) ||
        usableTitle(titleNode?.innerText) || usableTitle(titleNode?.textContent) ||
        titleFromLines(lines) || usableTitle(anchor?.getAttribute?.("aria-label"));
      const href = anchor?.getAttribute?.("href") || anchor?.getAttribute?.("ng-href") || "";
      const url = safeDetailUrl(href);
      const urlRecordId = (() => {
        try { return new URL(url).searchParams.get("docid"); } catch (_error) { return null; }
      })();
      const recordId = urlRecordId || idMatch?.[1] || null;
      if (!url && anchor) unsafe += 1;
      if (!recordId) missingRecordId += 1;
      if (!title) missingTitle += 1;
      if (!url) missingDetailUrl += 1;
      if (!recordId || !title || !url) {
        incomplete += 1;
        continue;
      }
      const resourceType = lines.find((line) => /^(?:book|journal|article|audio cd|video|newspaper article|book chapter|multiple versions)$/i.test(line)) || null;
      const availability = lines.find((line) => /\b(?:available at|online access|no online access|checked out)\b/i.test(line)) || null;
      const metadata = lines.filter((line) =>
        line !== title && line !== resourceType && line !== availability &&
        !/^\d+$/.test(line) && !/^(?:citation|e-mail|add item|show actions)/i.test(line)
      ).slice(0, 4).map((line) => line.slice(0, 500));
      results.push({
        record_id: recordId.slice(0, 120),
        title: title.slice(0, 500),
        resource_type: resourceType ? clean(resourceType).toLowerCase().replace(/\s+/g, "_") : "unknown",
        metadata,
        availability_label: availability ? availability.slice(0, 500) : null,
        detail_url: url
      });
    }
    const bodyText = clean(documentObject.body?.innerText || documentObject.body?.textContent);
    const emptyResultsMarkerFound = /\b(?:no records found|no results found|your search did not return any results)\b/i.test(bodyText);
    return {
      origin: PRIMO_ORIGIN,
      logged_in: null,
      page_kind: "catalog_results",
      result_count: results.length,
      results,
      diagnostics: {
        parser_version: VERSION,
        results_marker_found: candidates.length > 0 || emptyResultsMarkerFound,
        empty_results_marker_found: emptyResultsMarkerFound,
        result_candidate_count: candidates.length,
        parsed_result_count: results.length,
        incomplete_result_candidate_count: incomplete,
        unsafe_result_url_candidate_count: unsafe,
        missing_result_record_id_candidate_count: missingRecordId,
        missing_result_title_candidate_count: missingTitle,
        missing_result_detail_url_candidate_count: missingDetailUrl
      }
    };
  }

  function detailRecordId(locationObject) {
    try {
      const url = new URL(locationObject?.href || `${locationObject?.origin || ""}${locationObject?.pathname || ""}${locationObject?.search || ""}`);
      const value = url.searchParams.get("docid") || "";
      return /^[A-Za-z0-9_.:-]{3,120}$/.test(value) ? value : null;
    } catch (_error) {
      return null;
    }
  }

  function uniqueNodes(documentObject, selectors) {
    const nodes = [];
    const seen = new Set();
    for (const selector of selectors) {
      for (const node of documentObject.querySelectorAll?.(selector) || []) {
        if (!seen.has(node)) { seen.add(node); nodes.push(node); }
      }
    }
    return nodes;
  }

  function detailTitle(documentObject) {
    const selectors = [
      "[data-field-selector='title']", "[class*='item-title']", "[class*='item_title']",
      "prm-full-view h1", "prm-full-view h2", "main h1", "main h2", "h1", "h2"
    ];
    for (const node of uniqueNodes(documentObject, selectors)) {
      const title = usableTitle(node.innerText || node.textContent);
      if (title && !/^(?:find@hkul|full display(?: page)?|details|send to|links)$/i.test(title)) return title.slice(0, 500);
    }
    const lines = textLines(documentObject.body);
    return titleFromLines(lines)?.slice(0, 500) || null;
  }

  function detailMetadata(documentObject, title) {
    const rows = uniqueNodes(documentObject, [
      "table tr", "dl", "[class*='details-item']", "[class*='full-view-section'] [layout='row']"
    ]);
    const metadata = [];
    for (const row of rows) {
      const cells = [...(row.querySelectorAll?.("th, td, dt, dd, [class*='label'], [class*='value']") || [])]
        .map((cell) => clean(cell.innerText || cell.textContent)).filter(Boolean);
      let label = cells[0] || null;
      let value = cells.slice(1).join(" ") || null;
      if ((!label || !value) && cells.length === 0) {
        const lines = textLines(row);
        label = lines[0] || null;
        value = lines.slice(1).join(" ") || null;
      }
      if (!label || !value || label === value || value === title) continue;
      if (/^(?:qr|online access|availability|send to|actions?|sign in|to request,? please|locate|summary holdings:?|item in place\b.*|main library\b.*)$/i.test(label)) continue;
      if (/^(?:sign in|locate direct(?: \(beta\))?)$/i.test(value) ||
          /^available from\b/i.test(value) || /\bshow license\b/i.test(value)) continue;
      const key = `${label.toLowerCase()}|${value.toLowerCase()}`;
      if (!metadata.some((item) => item._key === key)) {
        metadata.push({ _key: key, label: label.slice(0, 120), value: value.slice(0, 1000) });
      }
      if (metadata.length >= 20) break;
    }
    for (const item of metadata) delete item._key;
    return metadata;
  }

  function accessKind(label) {
    if (/\b(?:online access|available online|full text|view online|electronic resource)\b/i.test(label)) return "online";
    if (/\b(?:available at|main library|storage|call number|location|loan desk|special collections)\b/i.test(label)) return "physical";
    return "unknown";
  }

  function accessState(label) {
    if (/\b(?:no online access|unavailable|not available|checked out)\b/i.test(label)) return "unavailable";
    if (/\b(?:online access|available at|available online|full text available|view online)\b/i.test(label)) return "available";
    return "unknown";
  }

  function detailAccessOptions(documentObject, title) {
    const nodes = uniqueNodes(documentObject, [
      "a", "button", "[class*='availability']", "[class*='locations']", "[class*='getit']", "[class*='service']"
    ]);
    const options = [];
    let unsafeLinkCandidates = 0;
    for (const node of nodes) {
      let label = clean(node.innerText || node.textContent || node.getAttribute?.("aria-label"));
      if (!label || !/\b(?:online access|available online|full text|view online|available at|main library|storage|call number|location|checked out|no online access)\b/i.test(label)) continue;
      if (/\bSEND TO\b.*\bSEARCH INSIDE\b.*\bGET IT\b/i.test(label)) continue;
      const hasOnline = /\b(?:online access|available online|full text|view online)\b/i.test(label);
      const hasPhysical = /\b(?:available at|main library|storage|call number|location)\b/i.test(label);
      if (hasOnline && hasPhysical) continue;
      if (title && label.toLowerCase().startsWith(title.toLowerCase())) {
        label = clean(label.slice(title.length));
      }
      if (!label) continue;
      const href = clean(node.getAttribute?.("href"));
      if (href && !safeDetailUrl(href)) unsafeLinkCandidates += 1;
      const kind = accessKind(label);
      const state = accessState(label);
      const normalized = label.replace(/,?\s*opens in a new window\s*$/i, "").trim().slice(0, 500);
      const key = `${kind}|${state}|${normalized.toLowerCase()}`;
      if (!options.some((option) => option._key === key)) {
        options.push({ _key: key, kind, availability: state, label: normalized });
      }
      if (options.length >= 30) break;
    }
    const specificPhysicalLabels = options
      .filter((option) => option.kind === "physical" && option.availability !== "unknown")
      .map((option) => option.label.toLowerCase());
    const filtered = options.filter((option) => !(
      option.kind === "physical" && option.availability === "unknown" &&
      specificPhysicalLabels.some((label) => label.includes(option.label.toLowerCase()))
    ));
    for (const option of filtered) delete option._key;
    return { options: filtered, unsafeLinkCandidates };
  }

  function parseResearchDetail(documentObject, locationObject) {
    if (locationObject?.origin !== PRIMO_ORIGIN || String(locationObject?.pathname || "").toLowerCase() !== "/discovery/fulldisplay") {
      const error = new Error("Open a fixed Find@HKUL full-display page before reading item details.");
      error.code = "LIBRARY_ITEM_NOT_READY";
      throw error;
    }
    const recordId = detailRecordId(locationObject);
    const title = detailTitle(documentObject);
    const bodyText = clean(documentObject.body?.innerText || documentObject.body?.textContent);
    const detailMarkerFound = Boolean(recordId && title && /\b(?:details|availability|online access|send to|full display)\b/i.test(bodyText));
    const metadata = title ? detailMetadata(documentObject, title) : [];
    const access = detailAccessOptions(documentObject, title);
    return {
      origin: PRIMO_ORIGIN,
      logged_in: null,
      page_kind: "catalog_item",
      record_id: recordId,
      title,
      resource_type: (textLines(documentObject.body).find((line) => /^(?:book|journal|article|audio cd|video|newspaper article|book chapter|multiple versions)$/i.test(line)) || "unknown").toLowerCase().replace(/\s+/g, "_"),
      metadata,
      access_options: access.options,
      detail_url: recordId ? safeDetailUrl(`/discovery/fulldisplay?docid=${encodeURIComponent(recordId)}`) : null,
      diagnostics: {
        parser_version: VERSION,
        detail_marker_found: detailMarkerFound,
        record_id_found: Boolean(recordId),
        title_found: Boolean(title),
        metadata_field_count: metadata.length,
        access_option_candidate_count: access.options.length,
        parsed_access_option_count: access.options.length,
        unsafe_access_link_candidate_count: access.unsafeLinkCandidates
      }
    };
  }

  function bookingDate(documentObject) {
    const text = clean(documentObject.body?.innerText || documentObject.body?.textContent);
    const match = text.match(/\b(20\d{2})[-/]([01]?\d)[-/]([0-3]?\d)\b/) ||
      text.match(/\b([0-3]?\d)[/]([01]?\d)[/](20\d{2})\b/);
    if (!match) return null;
    const year = match[1].length === 4 ? match[1] : match[3];
    const month = match[2];
    const day = match[1].length === 4 ? match[3] : match[1];
    return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }

  function optionText(select) {
    const options = [...(select?.options || select?.querySelectorAll?.("option") || [])];
    const selected = options.find((option) => option.selected) ||
      (Number.isInteger(select?.selectedIndex) ? options[select.selectedIndex] : null);
    return clean(selected?.textContent || selected?.innerText || "");
  }

  function bookingFilterSelects(documentObject) {
    const selects = [...(documentObject.querySelectorAll?.("select") || [])];
    const pageSelect = (select) => {
      const values = [...(select.options || select.querySelectorAll?.("option") || [])]
        .map((option) => clean(option.textContent || option.innerText))
        .filter(Boolean);
      return values.length > 0 && values.every((value) => /^\d+$/.test(value));
    };
    const candidates = selects.filter((select) => !pageSelect(select));
    const descriptor = (select) => clean([
      select.id,
      select.name,
      select.getAttribute?.("aria-label"),
      select.getAttribute?.("title")
    ].join(" ")).toLowerCase();
    const byHint = (pattern) => {
      const matches = candidates.filter((select) => pattern.test(descriptor(select)));
      return matches.length === 1 ? matches[0] : null;
    };
    const byLabel = (pattern) => {
      const matches = [];
      for (const label of documentObject.querySelectorAll?.("label") || []) {
        if (!pattern.test(clean(label.textContent || label.innerText).toLowerCase())) continue;
        const id = label.htmlFor || label.getAttribute?.("for");
        const control = label.control || (id ? documentObject.getElementById?.(id) : null);
        if (control && candidates.includes(control) && !matches.includes(control)) matches.push(control);
      }
      return matches.length === 1 ? matches[0] : null;
    };

    let location = byLabel(/^location\b/) || byHint(/(?:^|[_$-])(?:ddl|drp|select)?location(?:$|[_$-])/);
    let facilityType = byLabel(/^facility\s*type\b/) || byHint(/facility.*type|type.*facility/);
    let date = byLabel(/^date\b/) || byHint(/(?:^|[_$-])(?:ddl|drp|select)?date(?:$|[_$-])/);

    // The initial ASP.NET page exposes all three dependent controls with only
    // placeholder options, so a date-option heuristic cannot bootstrap Location.
    // Its stable form order is Location, Facility Type, Date; use that order only
    // after excluding the numeric result-page selector and only for exactly three.
    if ((!location || !facilityType || !date) && candidates.length === 3) {
      [location, facilityType, date] = candidates;
    }
    if (!location || !facilityType || !date || new Set([location, facilityType, date]).size !== 3) {
      return { location: null, facilityType: null, date: null };
    }
    return { location, facilityType, date };
  }

  function selectExact(select, expected, dateMode = false) {
    const normalized = clean(expected).toLowerCase();
    const options = [...(select?.options || select?.querySelectorAll?.("option") || [])];
    const matches = options.filter((option) => {
      const text = clean(option.textContent || option.innerText).toLowerCase();
      return dateMode ? text.startsWith(normalized) : text === normalized;
    });
    if (matches.length !== 1) {
      const error = new Error(`The exact booking filter '${expected}' was not uniquely available.`);
      error.code = matches.length ? "LIBRARY_SPACE_FILTER_AMBIGUOUS" : "LIBRARY_SPACE_FILTER_UNAVAILABLE";
      throw error;
    }
    const option = matches[0];
    if (optionText(select).toLowerCase() === clean(option.textContent || option.innerText).toLowerCase()) return false;
    select.value = option.value;
    const index = options.indexOf(option);
    if (index >= 0) select.selectedIndex = index;
    option.selected = true;
    const EventConstructor = select?.ownerDocument?.defaultView?.Event || globalThis.Event;
    if (typeof select.dispatchEvent === "function" && EventConstructor) {
      select.dispatchEvent(new EventConstructor("input", { bubbles: true }));
      select.dispatchEvent(new EventConstructor("change", { bubbles: true }));
    }
    return true;
  }

  function configureSpaceAvailability(documentObject, locationObject, payload, scheduler) {
    if (locationObject?.origin !== BOOKING_ORIGIN) {
      const error = new Error("Open the verified HKUL Facilities Booking System first.");
      error.code = "WRONG_LIBRARY_SPACE_PAGE";
      throw error;
    }
    const filters = bookingFilterSelects(documentObject);
    if (!filters.location || !filters.facilityType || !filters.date) {
      const error = new Error("The Location, Facility Type, and Date controls are not ready.");
      error.code = "LIBRARY_SPACE_FILTERS_NOT_READY";
      throw error;
    }
    const stages = [
      [filters.location, payload?.location, false, "location"],
      [filters.facilityType, payload?.booking_facility_type, false, "facility_type"],
      [filters.date, payload?.date, true, "date"]
    ];
    for (const [select, expected, dateMode, stage] of stages) {
      if (!clean(expected)) {
        const error = new Error(`Exact ${stage} is required for HKUL availability.`);
        error.code = "INVALID_INPUT";
        throw error;
      }
      if (selectExact(select, expected, dateMode)) {
        return { navigation_started: true, stage, availability_search_submitted: false };
      }
    }
    const bodyText = clean(documentObject.body?.innerText || documentObject.body?.textContent);
    const hasMatrix = [...(documentObject.querySelectorAll?.("table tr") || [])]
      .some((row) => [...(row.querySelectorAll?.("th,td") || [])]
        .some((cell) => Boolean(timeRange(cell.innerText || cell.textContent))));
    if (payload?.submit_search === true) {
      const controls = [...(documentObject.querySelectorAll?.("button, input[type='button'], input[type='submit']") || [])]
        .filter((node) => /^search$/i.test(clean(node.innerText || node.textContent || node.value)));
      if (controls.length !== 1) {
        const error = new Error("The exact HKUL availability Search control was not uniquely available.");
        error.code = controls.length ? "LIBRARY_SPACE_SEARCH_AMBIGUOUS" : "LIBRARY_SPACE_SEARCH_UNAVAILABLE";
        throw error;
      }
      const defer = scheduler || ((callback) => setTimeout(callback, 50));
      defer(() => controls[0].click());
      return { navigation_started: true, stage: "search", availability_search_submitted: true };
    }
    return {
      navigation_started: !hasMatrix,
      stage: hasMatrix ? "ready" : "results_wait",
      availability_search_submitted: false
    };
  }

  function formControls(documentObject) {
    const selects = [...(documentObject.querySelectorAll?.("select") || [])];
    const checkboxes = [...(documentObject.querySelectorAll?.("input[type='checkbox']") || [])];
    const buttons = [...(documentObject.querySelectorAll?.("button, input[type='submit'], input[type='button']") || [])];
    const labelFor = (control) => {
      const id = clean(control?.id);
      const labels = [...(documentObject.querySelectorAll?.("label") || [])]
        .filter((label) => (label.control === control) || (id && (label.htmlFor || label.getAttribute?.("for")) === id));
      if (labels.length === 1) return clean(labels[0].innerText || labels[0].textContent);
      const row = control?.closest?.("tr");
      const firstCell = row ? cellsOf(row)[0] : null;
      return clean(firstCell?.innerText || firstCell?.textContent);
    };
    const descriptor = (control) => clean([
      control?.id, control?.name, control?.getAttribute?.("aria-label"),
      control?.getAttribute?.("title"), labelFor(control)
    ].join(" ")).toLowerCase();
    return { selects, checkboxes, buttons, descriptor, labelFor };
  }

  function exactControl(form, candidates, pattern, label) {
    const matches = candidates.filter((control) => pattern.test(form.descriptor(control)));
    if (matches.length !== 1) {
      const error = new Error(`The exact ${label} control was not uniquely available.`);
      error.code = matches.length ? "LIBRARY_BOOKING_FORM_AMBIGUOUS" : "LIBRARY_BOOKING_FORM_INCOMPLETE";
      throw error;
    }
    return matches[0];
  }

  function bookingFormPage(documentObject, locationObject) {
    const bodyText = clean(documentObject?.body?.innerText || documentObject?.body?.textContent);
    return locationObject?.origin === BOOKING_ORIGIN && /\bnew booking\b/i.test(bodyText);
  }

  function bookingTargetValues(target) {
    return {
      location: clean(target?.location),
      floor: clean(target?.floor),
      facilityType: clean(target?.booking_facility_type),
      facility: clean(target?.room),
      date: clean(target?.date),
      start: clean(target?.start_time),
      end: clean(target?.end_time)
    };
  }

  function sessionRange(value) {
    const range = timeRange(value);
    if (range) return range;
    const match = clean(value).match(/\b([01]?\d|2[0-3]):([0-5]\d)\s*-\s*([01]?\d|2[0-3]):([0-5]\d)\b/);
    return match ? { start: `${match[1].padStart(2, "0")}:${match[2]}`, end: `${match[3].padStart(2, "0")}:${match[4]}` } : null;
  }

  function inspectBookingForm(documentObject, locationObject, target) {
    if (!bookingFormPage(documentObject, locationObject)) {
      const error = new Error("The authenticated HKUL New Booking form is not open.");
      error.code = "LIBRARY_BOOKING_FORM_NOT_READY";
      throw error;
    }
    const values = bookingTargetValues(target);
    if (Object.values(values).some((value) => !value)) {
      const error = new Error("The exact target is incomplete; all booking form fields and session times are required.");
      error.code = "INVALID_INPUT";
      throw error;
    }
    const controls = formControls(documentObject);
    const fieldPatterns = {
      location: /(?:^|\b)location\b/,
      floor: /(?:^|\b)floor\b/,
      facility_type: /facility\s*type|type\s*of\s*facility/,
      facility: /(?:^|\b)facility\b(?!\s*type)/,
      date: /(?:^|\b)date\b/
    };
    const selected = {};
    const fieldCounts = {};
    for (const [field, pattern] of Object.entries(fieldPatterns)) {
      const matches = controls.selects.filter((select) => pattern.test(controls.descriptor(select)));
      fieldCounts[field] = matches.length;
      if (matches.length === 1) selected[field] = optionText(matches[0]);
    }
    const sessionCandidates = controls.checkboxes.map((checkbox) => {
      const associated = [...(documentObject.querySelectorAll?.("label") || [])]
        .filter((label) => label.control === checkbox || (checkbox.id && (label.htmlFor || label.getAttribute?.("for")) === checkbox.id));
      const row = checkbox.closest?.("tr");
      const label = clean([
        ...associated.map((node) => node.innerText || node.textContent),
        checkbox.getAttribute?.("aria-label"), checkbox.value,
        row?.innerText || row?.textContent,
        checkbox.parentElement?.innerText || checkbox.parentElement?.textContent
      ].join(" "));
      const range = sessionRange(label);
      return { checkbox, label, range };
    }).filter((item) => item.range);
    const matchingSession = sessionCandidates.filter((item) =>
      item.range.start === values.start && item.range.end === values.end
    );
    const submitButtons = controls.buttons.filter((button) =>
      /^submit$/i.test(clean(button.innerText || button.textContent || button.value))
    );
    const selectedDate = clean(selected.date || "");
    const dateMatches = selectedDate.toLowerCase().startsWith(values.date.toLowerCase());
    const exactSessionSelected = matchingSession.length === 1 && matchingSession[0].checkbox.checked === true;
    const otherSessionsSelected = sessionCandidates.filter((item) => item.checkbox.checked &&
      !(item.range.start === values.start && item.range.end === values.end)).length;
    const bodyText = clean(documentObject.body?.innerText || documentObject.body?.textContent);
    const expectedFields = {
      location: selected.location === values.location,
      floor: selected.floor === values.floor,
      facility_type: selected.facility_type === values.facilityType,
      facility: selected.facility === values.facility,
      date: dateMatches
    };
    const ready = Object.values(expectedFields).every(Boolean) && exactSessionSelected &&
      otherSessionsSelected === 0 && submitButtons.length === 1 && submitButtons[0].disabled !== true;
    return {
      origin: BOOKING_ORIGIN,
      logged_in: true,
      page_kind: "new_booking",
      ready_to_submit: ready,
      exact_target_matches: expectedFields,
      selected_fields: selected,
      session: {
        start_time: matchingSession.length === 1 ? matchingSession[0].range.start : null,
        end_time: matchingSession.length === 1 ? matchingSession[0].range.end : null,
        exact_candidate_count: matchingSession.length,
        exact_session_selected: exactSessionSelected,
        other_selected_session_count: otherSessionsSelected
      },
      policy_notice_found: /deemed to accept the relevant policies|accept the relevant policies/i.test(bodyText),
      submit_button_candidate_count: submitButtons.length,
      diagnostics: {
        parser_version: BOOKING_FORM_VERSION,
        booking_form_marker_found: /new booking/i.test(bodyText),
        selected_field_candidate_counts: fieldCounts,
        session_candidate_count: sessionCandidates.length,
        exact_session_candidate_count: matchingSession.length
      }
    };
  }

  function configureBookingForm(documentObject, locationObject, target) {
    if (!bookingFormPage(documentObject, locationObject)) {
      const error = new Error("The authenticated HKUL New Booking form is not open.");
      error.code = "LIBRARY_BOOKING_FORM_NOT_READY";
      throw error;
    }
    const values = bookingTargetValues(target);
    const controls = formControls(documentObject);
    const stages = [
      [/\bLocation\b/i, values.location, false, "Location"],
      [/\bFloor\b/i, values.floor, false, "Floor"],
      [/facility\s*type|type\s*of\s*facility/i, values.facilityType, false, "Facility Type"],
      [/\bFacility\b(?!\s*Type)/i, values.facility, false, "Facility"],
      [/\bDate\b/i, values.date, true, "Date"]
    ];
    for (const [pattern, expected, dateMode, label] of stages) {
      const select = exactControl(controls, controls.selects, pattern, label);
      selectExact(select, expected, dateMode);
    }
    const inspection = inspectBookingForm(documentObject, locationObject, target);
    if (!inspection.session.exact_session_selected) {
      const sessionControls = controls.checkboxes.map((checkbox) => {
        const labels = [...(documentObject.querySelectorAll?.("label") || [])]
          .filter((label) => label.control === checkbox || (checkbox.id && (label.htmlFor || label.getAttribute?.("for")) === checkbox.id));
        const row = checkbox.closest?.("tr");
        const label = clean([
          ...labels.map((node) => node.innerText || node.textContent),
          checkbox.getAttribute?.("aria-label"), checkbox.value,
          row?.innerText || row?.textContent,
          checkbox.parentElement?.innerText || checkbox.parentElement?.textContent
        ].join(" "));
        const range = sessionRange(label);
        return { checkbox, range };
      }).filter((item) => item.range);
      const exact = sessionControls.filter((item) => item.range.start === values.start && item.range.end === values.end);
      const selectedOthers = sessionControls.filter((item) => item.checkbox.checked &&
        !(item.range.start === values.start && item.range.end === values.end));
      if (exact.length !== 1 || exact[0].checkbox.disabled || selectedOthers.length > 0) {
        const error = new Error("The exact session checkbox is not uniquely selectable without altering another selected session.");
        error.code = "LIBRARY_BOOKING_SESSION_MISMATCH";
        throw error;
      }
      exact[0].checkbox.checked = true;
      const EventConstructor = exact[0].checkbox?.ownerDocument?.defaultView?.Event || globalThis.Event;
      if (typeof exact[0].checkbox.dispatchEvent === "function" && EventConstructor) {
        exact[0].checkbox.dispatchEvent(new EventConstructor("input", { bubbles: true }));
        exact[0].checkbox.dispatchEvent(new EventConstructor("change", { bubbles: true }));
      }
    }
    return inspectBookingForm(documentObject, locationObject, target);
  }

  function clickExactAvailableSlot(documentObject, locationObject, target) {
    if (locationObject?.origin !== BOOKING_ORIGIN) {
      const error = new Error("Open the verified HKUL availability matrix first.");
      error.code = "WRONG_LIBRARY_SPACE_PAGE";
      throw error;
    }
    const values = bookingTargetValues(target);
    const availability = parseSpaceAvailability(documentObject, locationObject);
    if (availability.location !== values.location || availability.booking_facility_type !== values.facilityType ||
        availability.date !== values.date) {
      const error = new Error("Live HKUL availability filters do not match the confirmed booking target.");
      error.code = "LIBRARY_BOOKING_FILTER_MISMATCH";
      throw error;
    }
    const slotMatches = availability.available_slots.filter((slot) =>
      slot.room === values.facility && slot.floor === values.floor &&
      slot.start_time === values.start && slot.end_time === values.end
    );
    if (slotMatches.length !== 1) {
      const error = new Error("The exact available slot is not uniquely present in the refreshed HKUL matrix.");
      error.code = slotMatches.length ? "LIBRARY_BOOKING_SLOT_AMBIGUOUS" : "LIBRARY_BOOKING_SLOT_STALE";
      throw error;
    }
    const rows = [...(documentObject.querySelectorAll?.("table tr") || [])];
    let columns = new Map();
    for (const row of rows) {
      const ranges = new Map();
      cellsOf(row).forEach((cell, index) => {
        const range = timeRange(cell.innerText || cell.textContent);
        if (range) ranges.set(index, range);
      });
      if (ranges.size > columns.size) columns = ranges;
    }
    const candidates = [];
    for (const row of rows) {
      const cells = cellsOf(row);
      const floor = clean(cells[0]?.innerText || cells[0]?.textContent);
      const room = clean(cells[1]?.innerText || cells[1]?.textContent);
      if (floor !== values.floor || room !== values.facility) continue;
      for (const [index, range] of columns) {
        if (range.start !== values.start || range.end !== values.end) continue;
        const cell = cells[index];
        if (!cell || colorStatus(cell, /\bAvailable\b/i.test(clean(documentObject.body?.innerText || documentObject.body?.textContent)) &&
            /\bBooked\b/i.test(clean(documentObject.body?.innerText || documentObject.body?.textContent))) !== "available") continue;
        const descendants = [...(cell.querySelectorAll?.("a,button,input,[role='button'],[onclick]") || [])];
        const clickable = (descendants.length ? descendants : (interactiveCell(cell) ? [cell] : []))
          .filter((node) => /^select$/i.test(clean(node.innerText || node.textContent || node.value || node.getAttribute?.("aria-label"))));
        if (clickable.length === 1) candidates.push(clickable[0]);
      }
    }
    if (candidates.length !== 1) {
      const error = new Error("The exact green Select control was not uniquely identified.");
      error.code = candidates.length ? "LIBRARY_BOOKING_SELECT_AMBIGUOUS" : "LIBRARY_BOOKING_SELECT_UNAVAILABLE";
      throw error;
    }
    candidates[0].click();
    return { slot_selection_performed: true, candidate_count: 1, target_matches: true };
  }

  function submitBookingOnce(documentObject, locationObject, target) {
    const inspection = inspectBookingForm(documentObject, locationObject, target);
    if (!inspection.ready_to_submit || !inspection.policy_notice_found) {
      const error = new Error("The live form no longer matches the confirmed booking target; Submit was not clicked.");
      error.code = "LIBRARY_BOOKING_FORM_MISMATCH";
      throw error;
    }
    const controls = formControls(documentObject);
    const buttons = controls.buttons.filter((button) =>
      /^submit$/i.test(clean(button.innerText || button.textContent || button.value)) && button.disabled !== true
    );
    if (buttons.length !== 1) {
      const error = new Error("The exact booking Submit control was not uniquely available.");
      error.code = "LIBRARY_BOOKING_SUBMIT_AMBIGUOUS";
      throw error;
    }
    buttons[0].click();
    return { submit_click_dispatched: true, submit_button_candidate_count: 1 };
  }

  function openBookingRecord(documentObject, locationObject) {
    if (locationObject?.origin !== BOOKING_ORIGIN) {
      const error = new Error("Open the authenticated HKUL booking system first.");
      error.code = "WRONG_LIBRARY_BOOKING_PAGE";
      throw error;
    }
    const links = [...(documentObject.querySelectorAll?.("a") || [])].filter((node) =>
      /^my booking record$/i.test(clean(node.innerText || node.textContent))
    );
    if (links.length !== 1) {
      const error = new Error("The My Booking Record link was not uniquely available.");
      error.code = links.length ? "LIBRARY_BOOKING_RECORD_LINK_AMBIGUOUS" : "LIBRARY_BOOKING_RECORD_NOT_READY";
      throw error;
    }
    const href = links[0].getAttribute?.("href") || "";
    let url;
    try { url = new URL(href, locationObject.href); } catch (_error) { url = null; }
    if (!url || url.origin !== BOOKING_ORIGIN || !url.pathname.startsWith("/")) {
      const error = new Error("The My Booking Record destination is not on the fixed HKUL booking origin.");
      error.code = "UNSAFE_LIBRARY_BOOKING_RECORD_ROUTE";
      throw error;
    }
    links[0].click();
    return { navigation_started: true };
  }

  function verifyBookingRecord(documentObject, locationObject, target) {
    if (locationObject?.origin !== BOOKING_ORIGIN) {
      const error = new Error("The booking record did not remain on the HKUL booking origin.");
      error.code = "WRONG_LIBRARY_BOOKING_PAGE";
      throw error;
    }
    const values = bookingTargetValues(target);
    const bodyText = clean(documentObject.body?.innerText || documentObject.body?.textContent).toLowerCase();
    const rows = [...(documentObject.querySelectorAll?.("table tr") || [])];
    const [year, month, day] = values.date.split("-");
    const dateNeedles = [values.date.toLowerCase(), `${day}/${month}/${year}`, `${day}-${month}-${year}`];
    const roomNumber = values.facility.match(/\bRoom\s*([A-Za-z0-9-]+)\s*$/i)?.[1]?.toLowerCase() || null;
    const roomNeedle = values.facility.toLowerCase();
    let matchingCount = 0;
    for (const row of rows) {
      const text = clean(row.innerText || row.textContent).toLowerCase();
      const hasDate = dateNeedles.some((needle) => text.includes(needle));
      const hasRoom = text.includes(roomNeedle) || (roomNumber && new RegExp(`\\broom\\s*${roomNumber}\\b`, "i").test(text));
      const hasTimes = text.includes(values.start.toLowerCase()) && text.includes(values.end.toLowerCase());
      if (hasDate && hasRoom && hasTimes && !/\b(?:cancelled|canceled|rejected|expired)\b/i.test(text)) {
        // Count each visible active row. Text-deduplicating here could hide
        // two genuinely distinct reservations for the same target.
        matchingCount += 1;
      }
    }
    const isRecordPage = /my booking record|booking record|my bookings/i.test(bodyText) && rows.length > 0;
    return {
      origin: BOOKING_ORIGIN,
      logged_in: true,
      page_kind: isRecordPage ? "booking_record" : "booking_outcome_pending",
      record_page_marker_found: isRecordPage,
      exact_target_match_count: matchingCount,
      verified_exactly_once: isRecordPage && matchingCount === 1,
      diagnostics: {
        parser_version: BOOKING_FORM_VERSION,
        record_marker_found: isRecordPage,
        record_row_count: rows.length,
        exact_target_candidate_count: matchingCount
      }
    };
  }

  function timeRange(value) {
    const match = clean(value).match(/\b([01]?\d|2[0-3]):([0-5]\d)\s*(?:-|\u2013|\u2014|to)\s*([01]?\d|2[0-3]):([0-5]\d)\b/i);
    return match ? {
      start: `${match[1].padStart(2, "0")}:${match[2]}`,
      end: `${match[3].padStart(2, "0")}:${match[4]}`
    } : null;
  }

  function cellsOf(row) {
    try { return [...(row.querySelectorAll?.("th, td") || [])]; } catch (_error) { return []; }
  }

  function colorOf(node) {
    const direct = clean(node?.style?.backgroundColor || node?.getAttribute?.("bgcolor") || node?.getAttribute?.("data-color"));
    if (direct) return direct.toLowerCase();
    try {
      const view = node?.ownerDocument?.defaultView || root;
      return clean(view?.getComputedStyle?.(node)?.backgroundColor).toLowerCase();
    } catch (_error) {
      return "";
    }
  }

  function rgbOf(value) {
    const color = clean(value).toLowerCase();
    let match = color.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)/);
    if (match) {
      if (match[4] !== undefined && Number(match[4]) === 0) return null;
      return match.slice(1, 4).map(Number);
    }
    match = color.match(/^#([0-9a-f]{6})$/i);
    if (match) return [0, 2, 4].map((offset) => parseInt(match[1].slice(offset, offset + 2), 16));
    match = color.match(/^#([0-9a-f]{3})$/i);
    if (match) return [...match[1]].map((digit) => parseInt(digit + digit, 16));
    return null;
  }

  function directColorStatus(node, legendsFound) {
    const text = clean(node?.innerText || node?.textContent || node?.getAttribute?.("title") || node?.getAttribute?.("aria-label"));
    const className = clean(node?.className);
    if (/\b(?:available|vacant)\b/i.test(`${text} ${className}`) && !/\b(?:unavailable|not available)\b/i.test(text)) return "available";
    if (/\b(?:booked|unavailable|not available)\b/i.test(`${text} ${className}`)) return "booked";
    if (!legendsFound) return null;
    return statusFromRgb(rgbOf(colorOf(node)));
  }

  function statusFromRgb(rgb) {
    if (!rgb) return null;
    const [red, green, blue] = rgb;
    if (green >= 70 && green > red * 1.15 && green > blue * 1.15) return "available";
    if (red >= 100 && red > green * 1.12 && red > blue * 1.12) return "booked";
    return null;
  }

  function colorStatus(node, legendsFound) {
    const direct = directColorStatus(node, legendsFound);
    if (!legendsFound) return direct;
    // The grid may paint an inner control or its row while the td is transparent.
    const descendants = [...(node?.querySelectorAll?.("a,button,input,span,div") || [])].slice(0, 24);
    const ancestorEvidence = [];
    let ancestor = node?.parentElement;
    for (let depth = 0; ancestor && depth < 4; depth += 1, ancestor = ancestor.parentElement) {
      if (/^(?:table|tbody|thead|tfoot)$/i.test(String(ancestor.tagName || ""))) break;
      ancestorEvidence.push(statusFromRgb(rgbOf(colorOf(ancestor))));
      if (/^tr$/i.test(String(ancestor.tagName || ""))) break;
    }
    const evidence = [
      direct,
      ...descendants.map((child) => directColorStatus(child, legendsFound)),
      ...ancestorEvidence
    ].filter(Boolean);
    return evidence.length && evidence.every((status) => status === evidence[0]) ? evidence[0] : null;
  }

  function transparentColor(value) {
    const match = clean(value).toLowerCase().match(/^rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([\d.]+)\s*\)$/);
    return Boolean(match && Number(match[1]) === 0);
  }

  function interactiveCell(node) {
    if (!node) return false;
    const style = node?.ownerDocument?.defaultView?.getComputedStyle?.(node);
    if (node.onclick || node.getAttribute?.("onclick") || node.getAttribute?.("role") === "button" ||
        node.hasAttribute?.("tabindex") || /pointer/i.test(clean(style?.cursor))) return true;
    return Boolean(node.querySelector?.("a,button,input,[role='button'],[onclick],[tabindex]"));
  }

  function unknownCellShape(node, rowIndex, columnIndex) {
    const value = clean(node?.innerText || node?.textContent || "");
    const rgb = rgbOf(colorOf(node));
    let colorFamily = "unreadable";
    if (rgb) {
      if (rgb.every((channel) => channel >= 245)) colorFamily = "white";
      else if (rgb.every((channel) => channel <= 40)) colorFamily = "dark";
      else colorFamily = "other";
    }
    return {
      row_index: rowIndex,
      column_index: columnIndex,
      text_present: Boolean(value),
      interactive: interactiveCell(node),
      color_family: colorFamily,
      colspan: Math.min(100, Math.max(1, Number(node?.colSpan || node?.getAttribute?.("colspan") || 1) || 1))
    };
  }

  function neutralNonSelectableCell(node) {
    const text = clean(node?.innerText || node?.textContent || "");
    if (text && !/^(?:n\/?a|[-\u2013\u2014]+)$/i.test(text)) return false;
    if (interactiveCell(node)) return false;
    const descendants = [...(node?.querySelectorAll?.("a,button,input,span,div") || [])].slice(0, 24);
    if ([node, ...descendants].some((candidate) => directColorStatus(candidate, true))) return false;
    const color = colorOf(node);
    const rgb = rgbOf(color);
    if (rgb && rgb.every((channel) => channel >= 245)) return true;
    return transparentColor(color);
  }

  function resultPageSelect(documentObject) {
    const matches = [...(documentObject.querySelectorAll?.("select") || [])].filter((select) => {
      const values = [...(select.options || select.querySelectorAll?.("option") || [])]
        .map((option) => clean(option.textContent || option.innerText));
      return values.length > 0 && values.every((value) => /^\d+$/.test(value));
    });
    return matches.length === 1 ? matches[0] : null;
  }

  function matrixSignature(rows) {
    let hash = 2166136261;
    for (const row of rows) {
      for (const cell of cellsOf(row)) {
        const value = `${clean(cell.innerText || cell.textContent)}|${colorOf(cell)}|`;
        for (let index = 0; index < value.length; index += 1) {
          hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
        }
      }
    }
    return (hash >>> 0).toString(16).padStart(8, "0");
  }

  function selectSpaceResultPage(documentObject, locationObject, payload) {
    if (locationObject?.origin !== BOOKING_ORIGIN) {
      const error = new Error("Open the verified HKUL availability page first.");
      error.code = "WRONG_LIBRARY_SPACE_PAGE";
      throw error;
    }
    const page = Number(payload?.page_number);
    const select = resultPageSelect(documentObject);
    const options = [...(select?.options || select?.querySelectorAll?.("option") || [])];
    const matching = options.filter((option) => Number(clean(option.textContent || option.innerText)) === page);
    if (!Number.isInteger(page) || page < 1 || !select || matching.length !== 1) {
      const error = new Error("The requested HKUL result page is not uniquely available.");
      error.code = "LIBRARY_SPACE_RESULT_PAGE_UNAVAILABLE";
      throw error;
    }
    if (Number(optionText(select)) === page) return { navigation_started: false, page_number: page };
    const option = matching[0];
    select.value = option.value;
    select.selectedIndex = options.indexOf(option);
    option.selected = true;
    const EventConstructor = select?.ownerDocument?.defaultView?.Event || globalThis.Event;
    if (typeof select.dispatchEvent === "function" && EventConstructor) {
      select.dispatchEvent(new EventConstructor("input", { bubbles: true }));
      select.dispatchEvent(new EventConstructor("change", { bubbles: true }));
    }
    return { navigation_started: true, page_number: page };
  }

  function libraryHoursStatus(value) {
    const label = clean(value);
    if (/\bclosed\b/i.test(label)) return "closed";
    if (/\b24\s*hours?\b/i.test(label) ||
        /\b(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*(?:am|pm)?\s*(?:-|\u2013|\u2014|to)\s*(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*(?:am|pm)?\b/i.test(label)) return "open";
    return null;
  }

  function parseHoursAndLocations(documentObject, locationObject) {
    const path = String(locationObject?.pathname || "").toLowerCase();
    if (locationObject?.origin !== LIBRARY_ORIGIN || !path.startsWith("/general/hours")) {
      const error = new Error("Open the official HKUL opening-hours page first.");
      error.code = "WRONG_LIBRARY_HOURS_PAGE";
      throw error;
    }
    const bodyText = clean(documentObject.body?.innerText || documentObject.body?.textContent);
    const hoursMarkerFound = /\bopening hours\b/i.test(bodyText);
    const emptyStateFound = /opening hours of the selected date is not available yet/i.test(bodyText);
    const rows = [...(documentObject.querySelectorAll?.("table tr") || [])];
    const locations = [];
    let headers = [];
    let candidates = 0;
    let placeholders = 0;
    for (const row of rows) {
      const cells = cellsOf(row).map((cell) => clean(cell.innerText || cell.textContent));
      if (!cells.length) continue;
      if (/^library$/i.test(cells[0])) {
        headers = cells.slice(1).map((value) => value.slice(0, 120));
        continue;
      }
      const name = cells[0];
      if (!name || /^(?:date|day|hours?|service counters?|[-\u2013\u2014]+)$/i.test(name)) continue;
      const periods = [];
      cells.slice(1).forEach((hoursLabel, index) => {
        const status = libraryHoursStatus(hoursLabel);
        if (!status) return;
        periods.push({
          period_label: (headers[index] || `period_${index + 1}`).slice(0, 120),
          hours_label: hoursLabel.slice(0, 200),
          status
        });
      });
      if (!periods.length) {
        if (cells.slice(1).some((value) => /^[-\u2013\u2014]+$/.test(value))) placeholders += 1;
        continue;
      }
      candidates += 1;
      const key = `${name.toLowerCase()}|${periods.map((period) => `${period.period_label}:${period.hours_label}`).join("|")}`;
      if (!locations.some((item) => item._key === key)) {
        locations.push({ _key: key, name: name.slice(0, 200), periods });
      }
    }
    for (const location of locations) delete location._key;
    return {
      origin: LIBRARY_ORIGIN,
      logged_in: null,
      page_kind: "library_hours",
      hours_available: locations.length > 0,
      location_count: locations.length,
      locations,
      source_url: "https://lib.hku.hk/general/hours/",
      diagnostics: {
        parser_version: HOURS_VERSION,
        hours_marker_found: hoursMarkerFound,
        empty_state_found: emptyStateFound,
        row_count: rows.length,
        location_candidate_count: candidates,
        parsed_location_count: locations.length,
        duplicate_location_candidate_count: Math.max(0, candidates - locations.length),
        placeholder_location_count: placeholders
      }
    };
  }

  function parseSpaceAvailability(documentObject, locationObject) {
    if (locationObject?.origin === LIBRARY_ORIGIN && String(locationObject?.pathname || "").toLowerCase().startsWith("/hkulauth/")) {
      const error = new Error("Complete HKUL authentication in Chrome before reading space availability.");
      error.code = "LIBRARY_LOGIN_REQUIRED";
      throw error;
    }
    if (locationObject?.origin !== BOOKING_ORIGIN) {
      const error = new Error("Open an HKUL Book a Space availability page first.");
      error.code = "WRONG_LIBRARY_SPACE_PAGE";
      throw error;
    }

    const bodyText = clean(documentObject.body?.innerText || documentObject.body?.textContent);
    const filters = bookingFilterSelects(documentObject);
    const selectedLocation = optionText(filters.location) || null;
    const selectedFacilityType = optionText(filters.facilityType) || null;
    const selectedDateText = optionText(filters.date);
    const availableLegendFound = /(?:=\s*)?\bAvailable\b/i.test(bodyText);
    const bookedLegendFound = /(?:=\s*)?\bBooked\b/i.test(bodyText);
    const legendsFound = availableLegendFound && bookedLegendFound;
    const rows = [...(documentObject.querySelectorAll?.("table tr") || [])];
    const slots = [];
    let incomplete = 0;
    let candidateCount = 0;
    let facilityRowCount = 0;
    let statusCellCount = 0;
    let unclassifiedStatusCellCount = 0;
    let neutralNonSelectableCellCount = 0;
    const unclassifiedCellShapes = [];
    let tableMatrixFound = false;
    const verifiedEmptyResultFound = /\b(?:no\s+(?:facilities|rooms?|slots?|records?)\s+(?:found|available)|no\s+matching\s+(?:facilities|rooms?|slots?)|no\s+data\s+(?:found|available))\b/i.test(bodyText);

    let timeColumns = new Map();
    for (const row of rows) {
      const cells = cellsOf(row);
      const candidateColumns = new Map();
      cells.forEach((cell, index) => {
        const range = timeRange(cell.innerText || cell.textContent);
        if (range) candidateColumns.set(index, range);
      });
      if (candidateColumns.size > timeColumns.size) timeColumns = candidateColumns;
    }

    if (timeColumns.size) {
      tableMatrixFound = true;
      for (const [rowIndex, row] of rows.entries()) {
        const cells = cellsOf(row);
        if (cells.length < 3) continue;
        const floor = clean(cells[0]?.innerText || cells[0]?.textContent) || null;
        const room = clean(cells[1]?.innerText || cells[1]?.textContent) || null;
        if (!room || /^(?:facility|room)$/i.test(room)) continue;
        facilityRowCount += 1;
        for (const [index, range] of timeColumns) {
          const cell = cells[index];
          if (!cell) continue;
          statusCellCount += 1;
          const status = colorStatus(cell, legendsFound);
          if (!status) {
            if (neutralNonSelectableCell(cell)) neutralNonSelectableCellCount += 1;
            else {
              unclassifiedStatusCellCount += 1;
              if (unclassifiedCellShapes.length < 8) unclassifiedCellShapes.push(unknownCellShape(cell, rowIndex, index));
            }
            continue;
          }
          candidateCount += 1;
          if (status !== "available") continue;
          const key = `${floor || ""}|${room}|${range.start}|${range.end}`;
          if (!slots.some((slot) => slot._key === key)) {
            slots.push({ _key: key, floor: floor?.slice(0, 80) || null, room: room.slice(0, 200), start_time: range.start, end_time: range.end, status: "available" });
          }
        }
      }
    }

    const nodes = [];
    const seen = new Set();
    for (const selector of ["[data-start-time]", "[data-timeslot]", ".timeslot", ".slot"]) {
      for (const node of documentObject.querySelectorAll?.(selector) || []) {
        if (!seen.has(node)) { seen.add(node); nodes.push(node); }
      }
    }
    for (const node of nodes) {
      const text = clean(node.innerText || node.textContent);
      if (!/\b(?:available|vacant|book)\b/i.test(text) || /\b(?:unavailable|not available|fully booked)\b/i.test(text)) continue;
      candidateCount += 1;
      const range = timeRange(text);
      const explicitStart = clean(node.dataset?.startTime || node.getAttribute?.("data-start-time"));
      const explicitEnd = clean(node.dataset?.endTime || node.getAttribute?.("data-end-time"));
      const start = range?.start || (/^\d{2}:\d{2}$/.test(explicitStart) ? explicitStart : null);
      const end = range?.end || (/^\d{2}:\d{2}$/.test(explicitEnd) ? explicitEnd : null);
      if (!start || !end) { incomplete += 1; continue; }
      const room = clean(node.dataset?.room || node.getAttribute?.("data-room") || node.querySelector?.("[data-room], .room, .facility")?.textContent) || null;
      const key = `${room || ""}|${start}|${end}`;
      if (!slots.some((slot) => slot._key === key)) slots.push({ _key: key, floor: null, room: room?.slice(0, 200) || null, start_time: start, end_time: end, status: "available" });
    }

    for (const slot of slots) delete slot._key;
    const lastUpdatedMatch = bodyText.match(/Last\s+Updated\s*:\s*(20\d{2}-[01]\d-[0-3]\d\s+[0-2]\d:[0-5]\d:[0-5]\d)/i);
    const pageSelect = resultPageSelect(documentObject);
    const pageOptions = [...(pageSelect?.options || pageSelect?.querySelectorAll?.("option") || [])];
    const pageNumber = Number(optionText(pageSelect) || 1);
    const pageCount = Math.max(1, pageOptions.length || 1);
    const parsedDate = selectedDateText.match(/\b20\d{2}-[01]\d-[0-3]\d\b/)?.[0] || bookingDate(documentObject);
    for (const slot of slots) slot.page_number = pageNumber;
    return {
      origin: BOOKING_ORIGIN,
      logged_in: true,
      page_kind: "space_availability",
      location: selectedLocation,
      booking_facility_type: selectedFacilityType,
      date: parsedDate,
      source_last_updated_at: lastUpdatedMatch?.[1] || null,
      page_number: pageNumber,
      page_count: pageCount,
      result_set_complete: pageCount === 1,
      available_slot_count: slots.length,
      available_slots: slots.slice(0, 1000),
      diagnostics: {
        parser_version: VERSION,
        availability_marker_found: /\b(?:facilities booking system|book a space|facility status|new booking)\b/i.test(bodyText),
        availability_legend_found: availableLegendFound,
        booked_legend_found: bookedLegendFound,
        table_matrix_found: tableMatrixFound,
        matrix_signature: matrixSignature(rows),
        selected_filters_found: Boolean(selectedLocation && selectedFacilityType && parsedDate),
        result_set_complete: pageCount === 1,
        verified_empty_result_found: verifiedEmptyResultFound,
        facility_row_count: facilityRowCount,
        status_cell_count: statusCellCount,
        unclassified_status_cell_count: unclassifiedStatusCellCount,
        unclassified_cell_shapes: unclassifiedCellShapes,
        neutral_nonselectable_cell_count: neutralNonSelectableCellCount,
        slot_candidate_count: candidateCount,
        parsed_available_slot_count: slots.length,
        incomplete_available_slot_candidate_count: incomplete
      }
    };
  }

  root.HKULibraryParser = { parseResearch, parseResearchDetail, parseSpaceAvailability, configureSpaceAvailability, selectSpaceResultPage, parseHoursAndLocations, safeDetailUrl, clickExactAvailableSlot, inspectBookingForm, configureBookingForm, submitBookingOnce, openBookingRecord, verifyBookingRecord };
  if (typeof module !== "undefined" && module.exports) module.exports = root.HKULibraryParser;
})(typeof self !== "undefined" ? self : this);
