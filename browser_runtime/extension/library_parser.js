(function (root) {
  "use strict";

  const PRIMO_ORIGIN = "https://julac-hku.primo.exlibrisgroup.com";
  const LIBRARY_ORIGIN = "https://lib.hku.hk";
  const BOOKING_ORIGIN = "https://booking.lib.hku.hk";
  const VERSION = "0.1.2";

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
    return String(node?.innerText || node?.textContent || "").split(/\n+/).map(clean).filter(Boolean);
  }

  function usableTitle(value) {
    const title = clean(value);
    if (!title || /^(?:view|open|show|details?|full display|view full display(?: details?)?)$/i.test(title)) return null;
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
    let match = color.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (match) return match.slice(1, 4).map(Number);
    match = color.match(/^#([0-9a-f]{6})$/i);
    if (match) return [0, 2, 4].map((offset) => parseInt(match[1].slice(offset, offset + 2), 16));
    match = color.match(/^#([0-9a-f]{3})$/i);
    if (match) return [...match[1]].map((digit) => parseInt(digit + digit, 16));
    return null;
  }

  function colorStatus(node, legendsFound) {
    const text = clean(node?.innerText || node?.textContent || node?.getAttribute?.("title") || node?.getAttribute?.("aria-label"));
    const className = clean(node?.className);
    if (/\b(?:available|vacant)\b/i.test(`${text} ${className}`) && !/\b(?:unavailable|not available)\b/i.test(text)) return "available";
    if (/\b(?:booked|unavailable|not available)\b/i.test(`${text} ${className}`)) return "booked";
    if (!legendsFound) return null;
    const rgb = rgbOf(colorOf(node));
    if (!rgb) return null;
    const [red, green, blue] = rgb;
    if (green >= 70 && green > red * 1.15 && green > blue * 1.15) return "available";
    if (red >= 100 && red > green * 1.12 && red > blue * 1.12) return "booked";
    return null;
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
    const availableLegendFound = /(?:=\s*)?\bAvailable\b/i.test(bodyText);
    const bookedLegendFound = /(?:=\s*)?\bBooked\b/i.test(bodyText);
    const legendsFound = availableLegendFound && bookedLegendFound;
    const rows = [...(documentObject.querySelectorAll?.("table tr") || [])];
    const slots = [];
    let incomplete = 0;
    let candidateCount = 0;
    let tableMatrixFound = false;

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
      for (const row of rows) {
        const cells = cellsOf(row);
        if (cells.length < 3) continue;
        const floor = clean(cells[0]?.innerText || cells[0]?.textContent) || null;
        const room = clean(cells[1]?.innerText || cells[1]?.textContent) || null;
        if (!room || /^(?:facility|room)$/i.test(room)) continue;
        for (const [index, range] of timeColumns) {
          const cell = cells[index];
          if (!cell) continue;
          const status = colorStatus(cell, legendsFound);
          if (!status) continue;
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
    return {
      origin: BOOKING_ORIGIN,
      logged_in: true,
      page_kind: "space_availability",
      date: bookingDate(documentObject),
      available_slot_count: slots.length,
      available_slots: slots.slice(0, 200),
      diagnostics: {
        parser_version: VERSION,
        availability_marker_found: /\b(?:facilities booking system|book a space|facility status|new booking)\b/i.test(bodyText),
        availability_legend_found: availableLegendFound,
        booked_legend_found: bookedLegendFound,
        table_matrix_found: tableMatrixFound,
        slot_candidate_count: candidateCount,
        parsed_available_slot_count: slots.length,
        incomplete_available_slot_candidate_count: incomplete
      }
    };
  }

  root.HKULibraryParser = { parseResearch, parseSpaceAvailability, safeDetailUrl };
  if (typeof module !== "undefined" && module.exports) module.exports = root.HKULibraryParser;
})(typeof self !== "undefined" ? self : this);
